#!/usr/bin/env python3
"""Trim a real snapshot into the committed test fixture.

    python tests/make_fixture.py --from ../run/snapshots/2026-08-17 \
                                 --to tests/fixtures/snapshot

The tests must run offline, so a real snapshot (about 40 MB of CROSS plus 7 MB
of HTS) is cut down to a few hundred rows per source and the manifests are
rewritten to describe what was actually kept.

Trimming rules, chosen so the fixture stays usable rather than merely small:

* `hts.jsonl` keeps a contiguous head slice. Contiguity is the point: duty
  rates are inherited by walking upward through preceding rows, and a fixture
  stitched from disjoint blocks would hand the walk the wrong ancestor.
* `correlation.csv` keeps whole HS2017 groups. Dropping part of a group would
  contradict its own `n_hs2022_candidates` column.
* `cross.jsonl` keeps the first rulings that actually carry a tariff code, and
  `csl.jsonl` a plain head slice; neither has cross-row structure. The tariff
  filter is there because a ruling with an empty `tariffs` list joins to
  nothing and would make the fixture useless for the triage layer.
* floors are set to half of what was kept, so the fixture passes the gate and a
  test still has room to push a value under the floor.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fleet.sync.manifest import (  # noqa: E402
    ALL_SOURCES,
    DATA_FILES,
    SNAPSHOT_FILE,
    Manifest,
    data_path,
    manifest_path,
    sha256_file,
    write_manifest,
)

HTS_ROWS = 400
CROSS_ROWS = 200
CSL_ROWS = 200
CORRELATION_HEAD_GROUPS = 40

#: HS2017 codes worth carrying beyond the head of the table: a clean split
#: (442010 -> 442011/442019), a partial-coverage target (442199 -> ex442120),
#: and the two basket codes that dominate the real dead-code population.
CORRELATION_KEEP = ("442010", "442199", "210690", "854370")


def head_lines(src: Path, dest: Path, limit: int, keep=None) -> int:
    kept = 0
    with src.open(encoding="utf-8") as fh_in, dest.open("w", encoding="utf-8") as fh_out:
        for line in fh_in:
            if kept >= limit:
                break
            if not line.strip():
                continue
            if keep is not None and not keep(json.loads(line)):
                continue
            fh_out.write(line)
            kept += 1
    return kept


def has_tariff(record: dict) -> bool:
    return bool(record.get("tariffs"))


def trim_correlation(src: Path, dest: Path) -> int:
    with src.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = list(reader)

    order = []
    for row in rows:
        if row["hs2017"] not in order:
            order.append(row["hs2017"])
    keep = set(order[:CORRELATION_HEAD_GROUPS]) | {
        code for code in CORRELATION_KEEP if code in order
    }
    kept = [row for row in rows if row["hs2017"] in keep]

    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)
    return len(kept)


def rewrite_manifest(src_dir: Path, dest_dir: Path, source: str, row_count: int) -> Manifest:
    original = json.loads(manifest_path(src_dir, source).read_text(encoding="utf-8"))
    path = data_path(dest_dir, source)
    size = path.stat().st_size
    manifest = Manifest(
        source=source,
        url=original["url"],
        fetched_at=original["fetched_at"],
        revision=original.get("revision"),
        row_count=row_count,
        bytes=size,
        sha256=sha256_file(path),
        min_rows=max(1, row_count // 2),
        min_bytes=max(1, size // 2),
        status="ok",
        # Frozen at zero on purpose: a fixture that ages out would turn the
        # whole suite red on a calendar date rather than on a code change.
        staleness_days=0,
    )
    write_manifest(dest_dir, manifest)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="src", required=True, type=Path)
    parser.add_argument("--to", dest="dest", required=True, type=Path)
    args = parser.parse_args(argv)

    src, dest = args.src, args.dest
    dest.mkdir(parents=True, exist_ok=True)

    counts = {
        "hts": head_lines(data_path(src, "hts"), data_path(dest, "hts"), HTS_ROWS),
        "cross": head_lines(
            data_path(src, "cross"), data_path(dest, "cross"), CROSS_ROWS, keep=has_tariff
        ),
        "csl": head_lines(data_path(src, "csl"), data_path(dest, "csl"), CSL_ROWS),
        "correlation": trim_correlation(
            data_path(src, "correlation"), data_path(dest, "correlation")
        ),
    }

    for source in ALL_SOURCES:
        manifest = rewrite_manifest(src, dest, source, counts[source])
        print(
            f"{source}: rows={manifest.row_count} bytes={manifest.bytes} "
            f"floors={manifest.min_rows}/{manifest.min_bytes}"
        )

    marker = json.loads((src / SNAPSHOT_FILE).read_text(encoding="utf-8"))
    marker["sources"] = list(ALL_SOURCES)
    (dest / SNAPSHOT_FILE).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {dest}/{SNAPSHOT_FILE} snapshot_id={marker['snapshot_id']}")
    print("files: " + ", ".join(sorted(DATA_FILES.values())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
