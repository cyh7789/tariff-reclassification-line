"""Fetch the current USITC Harmonized Tariff Schedule export.

    python -m fleet.sync.hts --out data/snapshots/2026-08-18

The REST endpoint hands back the whole schedule in one call (about 12 MB of
JSON, ~35,800 rows). Row order is preserved on write because it carries
meaning: duty rates are published sparsely and a row inherits its rate from the
nearest preceding row with a smaller `indent` (contract section 3.2).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

from fleet.sync import cli, http
from fleet.sync.gate import DataSourceUnhealthy
from fleet.sync.manifest import Manifest, build_manifest, data_path, utc_now, write_manifest

SOURCE = "hts"

EXPORT_URL = (
    "https://hts.usitc.gov/reststop/exportList"
    "?from=0100&to=9999&format=JSON&styles=false"
)
RELEASE_URL = "https://hts.usitc.gov/reststop/currentRelease"

MIN_ROWS = 30_000
MIN_BYTES = 1_000_000

_NON_DIGIT = re.compile(r"\D")


def normalize_code(raw: str | None) -> str:
    """'8543.70.9860' -> '8543709860'. Empty string for header rows."""
    if not raw:
        return ""
    return _NON_DIGIT.sub("", raw)


def _as_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def to_record(row: dict, row_index: int) -> dict:
    """One HTS export row in the shape contract section 1.2 fixes."""
    code = normalize_code(row.get("htsno"))
    units = row.get("units") or []
    return {
        "htsno": code or None,
        "indent": _as_int(row.get("indent")),
        "description": row.get("description") or "",
        "general": row.get("general") or "",
        "special": row.get("special") or "",
        "other": row.get("other") or "",
        "units": list(units),
        # Where the extra duty hangs. 783 rows point at a chapter 99 subheading and
        # for goods of the wrong origin that add-on dwarfs the base rate, so a rate
        # read without it is wrong rather than partial. `additional_duties` is the
        # agricultural safeguard column, populated on 512 rows in chapter 9904.
        # Upstream also ships a misspelt `addiitionalDuties` that is null on every
        # row; it is not carried, because a field that is always null invites a
        # reader to conclude there is nothing there.
        "footnotes": [
            {"columns": list(f.get("columns") or []),
             "value": (f.get("value") or "").strip(),
             "type": f.get("type") or ""}
            for f in (row.get("footnotes") or [])
            if (f.get("value") or "").strip()
        ],
        "additional_duties": (row.get("additionalDuties") or "").strip() or None,
        "row_index": row_index,
    }


def current_release(session: requests.Session) -> str:
    payload = http.get_json(session, RELEASE_URL, min_bytes=10, source=SOURCE)
    name = (payload or {}).get("name")
    if not name:
        raise DataSourceUnhealthy(f"{SOURCE}: currentRelease carries no 'name': {payload!r}")
    return name


def fetch(out_dir: Path, *, session: requests.Session | None = None) -> Manifest:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = session or http.new_session()

    fetched_at = utc_now()
    revision = current_release(session)
    response = http.get(session, EXPORT_URL, min_bytes=MIN_BYTES, source=SOURCE)

    try:
        rows = json.loads(response.text)
    except ValueError as exc:
        raise DataSourceUnhealthy(f"{SOURCE}: export is not valid JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise DataSourceUnhealthy(f"{SOURCE}: export is {type(rows).__name__}, expected a list")
    if len(rows) < MIN_ROWS:
        raise DataSourceUnhealthy(
            f"{SOURCE}: export has {len(rows)} rows, below the floor {MIN_ROWS}"
        )

    path = data_path(out_dir, SOURCE)
    with path.open("w", encoding="utf-8") as fh:
        for row_index, row in enumerate(rows):
            fh.write(json.dumps(to_record(row, row_index), ensure_ascii=False) + "\n")

    manifest = build_manifest(
        source=SOURCE,
        url=EXPORT_URL,
        snapshot_dir=out_dir,
        fetched_at=fetched_at,
        revision=revision,
        row_count=len(rows),
        min_rows=MIN_ROWS,
        min_bytes=MIN_BYTES,
        last_modified=response.last_modified,
    )
    write_manifest(out_dir, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = cli.build_parser(__doc__.splitlines()[0]).parse_args(argv)
    cli.report(fetch(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
