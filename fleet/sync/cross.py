"""Fetch CBP CROSS rulings.

    python -m fleet.sync.cross --out data/snapshots/2026-08-18            # incremental
    python -m fleet.sync.cross --out data/snapshots/2026-08-18 --full     # re-enumerate

CROSS publishes no bulk download and no "list everything" call. The only
listing surface is the undocumented search endpoint, and a full enumeration is
219 paged requests for ~218,600 rulings, so it is not the default: an
incremental run copies the previous snapshot's `cross.jsonl` forward and asks
the search endpoint only for rulings dated on or after the newest date already
held. `--full` re-enumerates from scratch and is what you run when the frame
term changes or a snapshot is being built from nothing.

Two traps live here. The search endpoint returns ruling numbers upper-case and
the detail endpoint returns them lower-case, so everything written out is
upper-cased (contract section 1.2); and `term` cannot be empty, so enumeration
rides on a broad frame term rather than a match-all.
"""

from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from datetime import date
from pathlib import Path

import requests

from fleet.sync import cli, http
from fleet.sync.gate import DataSourceUnhealthy
from fleet.sync.manifest import (
    DATA_FILES,
    Manifest,
    build_manifest,
    data_path,
    utc_now,
    write_manifest,
)

SOURCE = "cross"

SEARCH_URL = "https://rulings.cbp.gov/api/search"
RULING_PAGE = "https://rulings.cbp.gov/ruling/{number}"

#: Broadest frame term measured during research: 218,606 of the 221,496
#: searchable rulings. An empty term returns zero hits, so there is no
#: match-all; "merchandise" (214,573) and "classification" (200,866) cover less.
DEFAULT_TERM = "customs"
DEFAULT_PAGE_SIZE = 1000

MIN_ROWS = 200_000
MIN_BYTES = 20_000_000

_NON_DIGIT = re.compile(r"\D")


def normalize_tariff(raw: str | None) -> str:
    """'4202.92.9026' -> '4202929026'."""
    return _NON_DIGIT.sub("", raw or "")


def to_record(hit: dict) -> dict | None:
    """One search hit in the shape contract section 1.2 fixes.

    Returns None for a hit with no ruling number, which cannot be joined to
    anything downstream.
    """
    number = (hit.get("rulingNumber") or "").strip().upper()
    if not number:
        return None
    raw_date = hit.get("rulingDate") or ""
    tariffs = [normalize_tariff(t) for t in (hit.get("tariffs") or [])]
    related = [
        str(r).strip().upper() for r in (hit.get("relatedRulings") or []) if str(r).strip()
    ]
    return {
        "ruling_number": number,
        "ruling_date": raw_date[:10],
        "tariffs": [t for t in tariffs if t],
        "subject": hit.get("subject") or "",
        "category": hit.get("categories") or "",
        "related_rulings": related,
        "url": RULING_PAGE.format(number=number),
    }


def _search(
    session: requests.Session,
    *,
    term: str,
    page: int,
    page_size: int,
    from_date: str | None,
) -> dict:
    params = {
        "term": term,
        "collection": "ALL",
        "pageSize": page_size,
        "page": page,
    }
    if from_date:
        params["fromDate"] = from_date
    return http.get_json(session, SEARCH_URL, params=params, min_bytes=2, source=SOURCE)


def enumerate_rulings(
    session: requests.Session,
    *,
    term: str = DEFAULT_TERM,
    page_size: int = DEFAULT_PAGE_SIZE,
    from_date: str | None = None,
    max_pages: int | None = None,
    progress=None,
) -> list[dict]:
    """Page through the search endpoint and return records in server order."""
    first = _search(
        session, term=term, page=1, page_size=page_size, from_date=from_date
    )
    total = int(first.get("totalHits") or 0)
    pages = (total + page_size - 1) // page_size
    if max_pages is not None:
        pages = min(pages, max_pages)
    if progress:
        progress(f"totalHits={total} pageSize={page_size} pages={pages}")

    records: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max(pages, 1) + 1):
        payload = (
            first
            if page == 1
            else _search(
                session, term=term, page=page, page_size=page_size, from_date=from_date
            )
        )
        hits = payload.get("rulings") or []
        if not hits:
            break
        for hit in hits:
            record = to_record(hit)
            if record is None or record["ruling_number"] in seen:
                continue
            seen.add(record["ruling_number"])
            records.append(record)
        if progress and (page % 25 == 0 or page == pages):
            progress(f"page={page}/{pages} unique={len(records)}")
    return records


def read_records(path: Path) -> "OrderedDict[str, dict]":
    held: OrderedDict[str, dict] = OrderedDict()
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            held[record["ruling_number"]] = record
    return held


def find_base_snapshot(out_dir: Path) -> Path | None:
    """Newest sibling snapshot that already carries a cross.jsonl."""
    out_dir = Path(out_dir).resolve()
    parent = out_dir.parent
    if not parent.is_dir():
        return None
    candidates = [
        child
        for child in sorted(parent.iterdir(), reverse=True)
        if child.is_dir()
        and child.resolve() != out_dir
        and (child / DATA_FILES[SOURCE]).is_file()
    ]
    return candidates[0] if candidates else None


def newest_date(records) -> str | None:
    dates = [r.get("ruling_date") for r in records if r.get("ruling_date")]
    return max(dates) if dates else None


def fetch(
    out_dir: Path,
    *,
    session: requests.Session | None = None,
    full: bool = False,
    base_dir: Path | None = None,
    since: str | None = None,
    term: str = DEFAULT_TERM,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    min_rows: int = MIN_ROWS,
    min_bytes: int = MIN_BYTES,
    progress=None,
) -> Manifest:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = session or http.new_session()

    held: OrderedDict[str, dict] = OrderedDict()
    from_date = since
    if not full:
        base = Path(base_dir) if base_dir else find_base_snapshot(out_dir)
        if base is None:
            raise DataSourceUnhealthy(
                f"{SOURCE}: no previous snapshot to extend and --full not given; "
                f"a snapshot must carry every ruling, not just the recent ones"
            )
        held = read_records(base / DATA_FILES[SOURCE])
        if progress:
            progress(f"base={base} rulings={len(held)}")
        if from_date is None:
            # Re-ask for the newest day already held: rulings are added to a
            # date that is already in the file, so an exclusive cursor drops them.
            from_date = newest_date(held.values())

    fetched_at = utc_now()
    fresh = enumerate_rulings(
        session,
        term=term,
        page_size=page_size,
        from_date=from_date,
        max_pages=max_pages,
        progress=progress,
    )
    for record in fresh:
        held[record["ruling_number"]] = record

    if not held:
        raise DataSourceUnhealthy(f"{SOURCE}: enumeration produced zero rulings")

    path = data_path(out_dir, SOURCE)
    with path.open("w", encoding="utf-8") as fh:
        for record in held.values():
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    manifest = build_manifest(
        source=SOURCE,
        url=SEARCH_URL,
        snapshot_dir=out_dir,
        fetched_at=fetched_at,
        # CROSS publishes an update date rather than a revision label.
        revision=newest_date(held.values()),
        row_count=len(held),
        min_rows=min_rows,
        min_bytes=min_bytes,
        last_modified=None,
    )
    write_manifest(out_dir, manifest)
    if progress:
        progress(f"wrote {path} rulings={len(held)} new_or_updated={len(fresh)}")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = cli.build_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--full",
        action="store_true",
        help="re-enumerate every ruling instead of extending a previous snapshot",
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=None,
        help="snapshot to extend (default: newest sibling of --out that has cross.jsonl)",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="fetch rulings dated on or after this YYYY-MM-DD (default: newest date held)",
    )
    parser.add_argument("--term", default=DEFAULT_TERM, help="frame search term")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument(
        "--max-pages", type=int, default=None, help="stop after this many pages"
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=MIN_ROWS,
        help="row floor written into the manifest",
    )
    parser.add_argument(
        "--min-bytes",
        type=int,
        default=MIN_BYTES,
        help="byte floor written into the manifest",
    )
    args = parser.parse_args(argv)

    if args.since:
        date.fromisoformat(args.since)

    manifest = fetch(
        args.out,
        full=args.full,
        base_dir=args.base,
        since=args.since,
        term=args.term,
        page_size=args.page_size,
        max_pages=args.max_pages,
        min_rows=args.min_rows,
        min_bytes=args.min_bytes,
        progress=lambda msg: print(msg, file=sys.stderr, flush=True),
    )
    cli.report(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
