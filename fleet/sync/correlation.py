"""Build the HS2017 -> HS2022 correlation table.

    python -m fleet.sync.correlation --out data/snapshots/2026-08-18

This is the research phase's `fetch_sources.sh` + `parse_wco_table2.py` +
`build_correlation.py` moved into the package. The parsing is unchanged,
including the single WCO PDF typo correction (the row between 2933.33 and
2933.35 renders as `28933.34`; chapter 89 has no heading 8933 and UNSD carries
293339 -> 293334, so the intended code is 2933.34). The acceptance test is a
byte comparison against the table built during research.

Two sources, both required:

* UNSD `HS2022toHS2017ConversionAndCorrelationTables.xlsx` is the primary,
  machine-readable table. It covers all 5,386 correlated HS2017 codes;
* WCO Table II is a PDF and is the only place the `ex` partial-coverage markers
  exist. `pdftotext -layout` (poppler) turns it into the two-column text this
  parser expects, so poppler is a build-time dependency of this module alone.

Raw downloads land in a cache directory outside the snapshot, because the WCO
PDF and the UNSD workbook change on a multi-year cycle and re-downloading them
per snapshot buys nothing.
"""

from __future__ import annotations

import collections
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import openpyxl
import requests

from fleet.sync import cli, http
from fleet.sync.gate import DataSourceUnhealthy
from fleet.sync.manifest import Manifest, build_manifest, data_path, utc_now, write_manifest

SOURCE = "correlation"

UNSD_URL = (
    "https://unstats.un.org/unsd/classifications/Econ/tables/"
    "HS2022toHS2017ConversionAndCorrelationTables.xlsx"
)
WCO_TABLE_II_URL = (
    "https://wcoomd.org/-/media/wco/public/global/pdf/topics/nomenclature/"
    "instruments-and-tools/hs-nomenclature-2022/table-ii_en.pdf?la=en"
)

UNSD_MIN_BYTES = 200_000
WCO_MIN_BYTES = 200_000

MIN_ROWS = 15_000
MIN_BYTES = 400_000

UNSD_SHEET = "HS2022-HS2017 Correlations"

# ---------------------------------------------------------------------------
# WCO Table II parsing (ported from parse_wco_table2.py, behavior unchanged)
# ---------------------------------------------------------------------------

# A whitespace-delimited token that is a code, optionally "ex"-prefixed and
# optionally carrying a leading superscript footnote digit glued on by pdftotext
# (e.g. "28933.34" is footnote 2 + subheading 2933.34).
TOKEN = re.compile(r"^(ex)?(\d)?(\d{4}\.\d{2})$")
# 4-digit heading reference (e.g. "30.04"), not a 6-digit subheading.
# The lookarounds stop it matching the tail of a subheading ("2933.34").
HEADING = re.compile(r"(?<![\d.])\d{2}\.\d{2}(?!\d)")
# running headers, footers and page numbers
SKIP = re.compile(
    r"Version\s+20\d\d|Copyright|reproduction and adaptation|"
    r"CORRELATING|HARMONIZED|^\s*II/\d+\.\s*$|November 20\d\d"
)
# column index below which a token belongs to the 2017 (left) side
SPLIT_COL = 60

# UNSD pads its tables with a 999999 "not elsewhere classified" filler row.
FILLER = "999999"
# Single typographical error in the WCO PDF, see the module docstring.
WCO_TYPO = {("293339", "893334"): ("293339", "293334")}

# HS2022 created four headings that draw a sliver out of a very large number of
# old codes: 8524 (flat panel display modules), 8529, 8541, 8549 (e-waste).
# WCO Table II cannot enumerate the old side for these -- it prints prose
# ("Applicable subheadings, in particular in headings 84.13, 84.14, ..."), so
# every one of these pairs is UNSD-only. They are real, but they make almost
# every electrical code look ambiguous, so they are flagged for sensitivity.
SWEEP_HEADINGS = {"8524", "8529", "8541", "8549"}


def parse_table_ii(txt_path: Path):
    """Return (pairs, headings, deleted) from the pdftotext -layout dump."""
    pairs = []
    headings = []   # rows referring to a 4-digit heading rather than a subheading
    deleted = []    # 2017 codes whose right column is prose (e.g. "deleted")
    cur_old = None
    with Path(txt_path).open(encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    for line in lines:
        # Page furniture must be skipped, not treated as a group boundary:
        # correlation groups run across page breaks (0410.00 continues onto
        # the next page), so resetting on the footer silently drops pairs.
        if SKIP.search(line) or not line.strip():
            continue
        # pdftotext renders the partial-coverage marker both as "ex8549.31" and
        # as "ex 8549.31"; glue the spaced form so it is one token. The 1-2
        # character shift this causes cannot move a token across SPLIT_COL
        # (the two columns sit at ~38 and ~75).
        line = re.sub(r"\bex\s+(?=\d)", "ex", line)
        left_text, right_text = line[:SPLIT_COL], line[SPLIT_COL:]

        # A left column carrying prose ("Applicable subheadings, in particular
        # in headings 84.13, ...") or a bare 4-digit heading is a heading-level
        # group, not a 6-digit subheading. It must close the current group,
        # otherwise its right-hand codes get attached to the preceding code.
        if re.search(r"[A-Za-z]", left_text) or HEADING.search(left_text):
            if left_text.strip():
                cur_old = None
                headings.append(left_text.strip())
                continue

        left, right = [], []
        for m in re.finditer(r"\S+", line):
            tok, col = m.group(0), m.start()
            cm = TOKEN.match(tok)
            if not cm:
                continue
            is_ex = cm.group(1) is not None
            code = cm.group(3).replace(".", "")
            (left if col < SPLIT_COL else right).append((code, is_ex))

        if len(left) > 1 or len(right) > 1:
            raise ValueError(f"more than one code per column: {line!r}")

        if left:
            # left column in Table II is never "ex"-marked; assert that
            if left[0][1]:
                raise ValueError(f"unexpected ex on 2017 side: {line!r}")
            cur_old = left[0][0]
            if not right and re.search(r"[A-Za-z]", right_text):
                deleted.append(cur_old)
        if right and cur_old is not None:
            new_code, new_ex = right[0]
            pairs.append((cur_old, new_code, new_ex))
    return pairs, headings, deleted


def write_wco_pairs(pairs, out_path: Path) -> int:
    """Deduplicate on (hs2017, hs2022), first occurrence wins."""
    seen = set()
    with Path(out_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["hs2017", "hs2022", "new_is_ex"])
        for old, new, nex in pairs:
            if (old, new) in seen:
                continue
            seen.add((old, new))
            w.writerow([old, new, int(nex)])
    return len(seen)


# ---------------------------------------------------------------------------
# Correlation build (ported from build_correlation.py, behavior unchanged)
# ---------------------------------------------------------------------------


def load_unsd(xlsx_path: Path) -> dict:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb[UNSD_SHEET]
    pairs = {}
    for row in ws.iter_rows(min_row=3, values_only=True):
        new, old, rel = (str(c).strip() if c is not None else "" for c in row[:3])
        if not new or not old or FILLER in (new, old):
            continue
        pairs[(old, new)] = rel
    return pairs


def load_wco_ex(pairs_csv: Path) -> dict:
    ex = {}
    with Path(pairs_csv).open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = (r["hs2017"], r["hs2022"])
            key = WCO_TYPO.get(key, key)
            ex[key] = bool(int(r["new_is_ex"]))
    return ex


def classify(n_new, new_codes, old_degree):
    """Label a pair group from the HS2017 -> HS2022 direction.

    n_new       how many HS2022 codes this HS2017 code maps to
    old_degree  for each HS2022 code, how many HS2017 codes feed into it
    """
    merged = any(old_degree[c] > 1 for c in new_codes)
    if n_new == 1:
        return "n:1" if merged else "1:1"
    return "n:n" if merged else "1:n"


def build_rows(unsd: dict, ex: dict) -> list[dict]:
    new_by_old = collections.defaultdict(set)
    old_by_new = collections.defaultdict(set)
    for old, new in unsd:
        new_by_old[old].add(new)
        old_by_new[new].add(old)
    old_degree = {c: len(v) for c, v in old_by_new.items()}

    rows = []
    for (old, new), unsd_rel in sorted(unsd.items()):
        codes = new_by_old[old]
        in_wco = (old, new) in ex
        rows.append({
            "hs2017": old,
            "hs2022": new,
            "relationship": classify(len(codes), codes, old_degree),
            "n_hs2022_candidates": len(codes),
            "is_ex": int(ex.get((old, new), False)),
            "unsd_relationship": unsd_rel,
            "in_wco_table2": int(in_wco),
            "is_sweep": int(not in_wco and new[:4] in SWEEP_HEADINGS),
        })
    return rows


def write_correlation_csv(rows: list[dict], out_path: Path) -> None:
    with Path(out_path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def distribution(rows: list[dict]) -> dict:
    """The counts CORRELATION.md reports, kept for provenance."""
    per_old = {}
    for r in rows:
        per_old[r["hs2017"]] = r["relationship"]
    dist = collections.Counter(per_old.values())
    total = len(per_old)
    unique = sum(v for k, v in dist.items() if k in ("1:1", "n:1"))
    ambiguous = total - unique

    sweepless = collections.defaultdict(set)
    for r in rows:
        if not r["is_sweep"]:
            sweepless[r["hs2017"]].add(r["hs2022"])
    sw_unique = sum(1 for v in sweepless.values() if len(v) == 1)
    sw_total = len(sweepless)

    ex_olds = {r["hs2017"] for r in rows if r["is_ex"]}
    old_by_new = {r["hs2022"] for r in rows}

    return {
        "hs2017_codes_total": total,
        "hs2022_codes_total": len(old_by_new),
        "pairs_total": len(rows),
        "distribution_by_hs2017_code": dict(dist),
        "unique_lookup": unique,
        "unique_lookup_pct": round(100 * unique / total, 2),
        "needs_judgement": ambiguous,
        "needs_judgement_pct": round(100 * ambiguous / total, 2),
        "hs2017_codes_with_ex_target": len(ex_olds),
        "pairs_with_ex_target": sum(r["is_ex"] for r in rows),
        "unsd_label_distribution_by_pair": dict(
            collections.Counter(r["unsd_relationship"] for r in rows)),
        "max_candidates": max(r["n_hs2022_candidates"] for r in rows),
        "pairs_in_wco_table2": sum(r["in_wco_table2"] for r in rows),
        "pairs_sweep_only": sum(r["is_sweep"] for r in rows),
        "sensitivity_excluding_sweep_headings": {
            "hs2017_codes_total": sw_total,
            "unique_lookup": sw_unique,
            "unique_lookup_pct": round(100 * sw_unique / sw_total, 2),
            "needs_judgement": sw_total - sw_unique,
            "needs_judgement_pct": round(100 * (sw_total - sw_unique) / sw_total, 2),
        },
    }


# ---------------------------------------------------------------------------
# Fetch + build
# ---------------------------------------------------------------------------


def default_cache_dir(out_dir: Path) -> Path:
    return Path(out_dir).parent / "_cache" / SOURCE


def download_sources(
    cache_dir: Path,
    *,
    session: requests.Session | None = None,
    refresh: bool = False,
) -> tuple[Path, Path]:
    """Download the UNSD workbook and the WCO PDF into `cache_dir`."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    session = session or http.new_session()

    targets = [
        (UNSD_URL, cache_dir / "HS2022toHS2017.xlsx", UNSD_MIN_BYTES),
        (WCO_TABLE_II_URL, cache_dir / "wco_table_ii_hs2017_to_hs2022.pdf", WCO_MIN_BYTES),
    ]
    for url, dest, min_bytes in targets:
        if dest.is_file() and dest.stat().st_size >= min_bytes and not refresh:
            continue
        response = http.get(session, url, min_bytes=min_bytes, source=SOURCE)
        dest.write_bytes(response.body)
    return targets[0][1], targets[1][1]


def pdf_to_text(pdf_path: Path, txt_path: Path) -> Path:
    """`pdftotext -layout`, the same call the research shell script made."""
    if shutil.which("pdftotext") is None:
        raise DataSourceUnhealthy(
            f"{SOURCE}: pdftotext (poppler) is not installed; WCO publishes "
            f"Table II as a PDF only"
        )
    subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), str(txt_path)],
        check=True,
        capture_output=True,
    )
    if not txt_path.is_file() or txt_path.stat().st_size == 0:
        raise DataSourceUnhealthy(f"{SOURCE}: pdftotext produced no text for {pdf_path}")
    return txt_path


def build(
    cache_dir: Path,
    out_dir: Path,
    *,
    xlsx_path: Path | None = None,
    txt_path: Path | None = None,
) -> list[dict]:
    """Parse the cached sources and write correlation.csv into `out_dir`."""
    cache_dir = Path(cache_dir)
    xlsx_path = Path(xlsx_path) if xlsx_path else cache_dir / "HS2022toHS2017.xlsx"
    txt_path = Path(txt_path) if txt_path else cache_dir / "table_ii.txt"

    pairs, _headings, _deleted = parse_table_ii(txt_path)
    if not pairs:
        raise DataSourceUnhealthy(f"{SOURCE}: parsed zero pairs from {txt_path}")
    write_wco_pairs(pairs, cache_dir / "wco_table2_pairs.csv")

    unsd = load_unsd(xlsx_path)
    if not unsd:
        raise DataSourceUnhealthy(f"{SOURCE}: UNSD sheet {UNSD_SHEET!r} yielded no pairs")
    ex = load_wco_ex(cache_dir / "wco_table2_pairs.csv")

    rows = build_rows(unsd, ex)
    write_correlation_csv(rows, data_path(out_dir, SOURCE))
    (cache_dir / "distribution.json").write_text(
        json.dumps(distribution(rows), indent=2), encoding="utf-8"
    )
    return rows


def fetch(
    out_dir: Path,
    *,
    session: requests.Session | None = None,
    cache_dir: Path | None = None,
    refresh: bool = False,
) -> Manifest:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(cache_dir) if cache_dir else default_cache_dir(out_dir)

    fetched_at = utc_now()
    xlsx_path, pdf_path = download_sources(cache_dir, session=session, refresh=refresh)
    pdf_to_text(pdf_path, cache_dir / "table_ii.txt")
    rows = build(cache_dir, out_dir, xlsx_path=xlsx_path)

    manifest = build_manifest(
        source=SOURCE,
        url=UNSD_URL,
        snapshot_dir=out_dir,
        fetched_at=fetched_at,
        # Neither UNSD nor WCO stamps a revision on these tables.
        revision=None,
        row_count=len(rows),
        min_rows=MIN_ROWS,
        min_bytes=MIN_BYTES,
        last_modified=None,
    )
    write_manifest(out_dir, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = cli.build_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="where the UNSD workbook and WCO PDF are kept "
        "(default: <out>/../_cache/correlation)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-download the sources even when the cache already holds them",
    )
    args = parser.parse_args(argv)
    cli.report(fetch(args.out, cache_dir=args.cache, refresh=args.refresh))
    return 0


if __name__ == "__main__":
    sys.exit(main())
