"""Fetch the ITA Consolidated Screening List.

    python -m fleet.sync.csl --out data/snapshots/2026-08-18

The CSL is used instead of OFAC's own SDN export because it is a superset: the
19,199 SDN entries are in it verbatim, and it adds the BIS lists (Entity List,
Denied Persons, Unverified, Military End User) together with the
`license_requirement` and `license_policy` columns that an export-control call
actually needs. OFAC publishes no BIS data at all.

This is the source where a silent empty file is worst: an empty screening list
means every party passes screening. The byte and row floors, not the status
code, are what stop that.
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import requests

from fleet.sync import cli, http
from fleet.sync.gate import DataSourceUnhealthy
from fleet.sync.manifest import Manifest, build_manifest, data_path, utc_now, write_manifest

SOURCE = "csl"

CSV_URL = (
    "https://data.trade.gov/downloadable_consolidated_screening_list/v1/consolidated.csv"
)

MIN_ROWS = 20_000
MIN_BYTES = 1_000_000

#: The list a row came from, e.g. "Entity List (EL) - Bureau of Industry and
#: Security". The ITA CSV calls the column `source`; the contract calls the
#: field `source_list`.
SOURCE_COLUMN = "source"


def to_record(row: dict) -> dict:
    """Pass the ITA columns through, then add the two the contract names."""
    record = dict(row)
    record["source_list"] = row.get(SOURCE_COLUMN, "")
    record["license_requirement"] = row.get("license_requirement", "")
    return record


def fetch(out_dir: Path, *, session: requests.Session | None = None) -> Manifest:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = session or http.new_session()

    fetched_at = utc_now()
    # HEAD returns 404 on this host, so the size check has to ride on the GET.
    response = http.get(session, CSV_URL, min_bytes=MIN_BYTES, source=SOURCE)

    reader = csv.DictReader(io.StringIO(response.text))
    if not reader.fieldnames or SOURCE_COLUMN not in reader.fieldnames:
        raise DataSourceUnhealthy(
            f"{SOURCE}: CSV header has no {SOURCE_COLUMN!r} column: {reader.fieldnames!r}"
        )

    path = data_path(out_dir, SOURCE)
    row_count = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in reader:
            fh.write(json.dumps(to_record(row), ensure_ascii=False) + "\n")
            row_count += 1

    if row_count < MIN_ROWS:
        raise DataSourceUnhealthy(
            f"{SOURCE}: {row_count} entries, below the floor {MIN_ROWS}; refusing to "
            f"ship a screening list that would clear everyone"
        )

    manifest = build_manifest(
        source=SOURCE,
        url=CSV_URL,
        snapshot_dir=out_dir,
        fetched_at=fetched_at,
        revision=None,
        row_count=row_count,
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
