"""Drive all four fetchers and seal the snapshot.

    python -m fleet.sync.snapshot --out data/snapshots/2026-08-18

`SNAPSHOT.json` is written last and only after every source has produced a
manifest, because its presence is the only signal that a snapshot is complete
(contract section 1). The gate runs against the finished directory before this
command reports success, so a snapshot that would fail track B fails here first.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fleet.sync import cli, correlation, cross, csl, gate, hts
from fleet.sync.manifest import ALL_SOURCES, SNAPSHOT_FILE, Manifest, iso_utc, utc_now

FETCHERS = {
    "hts": hts.fetch,
    "cross": cross.fetch,
    "csl": csl.fetch,
    "correlation": correlation.fetch,
}


def write_snapshot_marker(out_dir: Path, sources, created_at) -> Path:
    path = Path(out_dir) / SNAPSHOT_FILE
    marker = {
        "snapshot_id": Path(out_dir).name,
        "created_at": iso_utc(created_at),
        "sources": list(sources),
        "status": "ok",
    }
    path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    return path


def build_snapshot(
    out_dir: Path,
    *,
    sources=ALL_SOURCES,
    cross_kwargs: dict | None = None,
    progress=None,
) -> dict[str, Manifest]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    created_at = utc_now()

    manifests: dict[str, Manifest] = {}
    for source in sources:
        if progress:
            progress(f"fetching {source}")
        kwargs = dict(cross_kwargs or {}) if source == "cross" else {}
        manifests[source] = FETCHERS[source](out_dir, **kwargs)
        if progress:
            manifest = manifests[source]
            progress(
                f"{source}: rows={manifest.row_count} bytes={manifest.bytes} "
                f"revision={manifest.revision}"
            )

    write_snapshot_marker(out_dir, sources, created_at)
    gate.assert_healthy(out_dir, list(sources))
    return manifests


def main(argv: list[str] | None = None) -> int:
    parser = cli.build_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--sources",
        default=",".join(ALL_SOURCES),
        help=f"comma-separated subset of {','.join(ALL_SOURCES)}",
    )
    parser.add_argument(
        "--full-cross",
        action="store_true",
        help="re-enumerate every CROSS ruling instead of extending a previous snapshot",
    )
    parser.add_argument(
        "--cross-base",
        type=Path,
        default=None,
        help="snapshot whose cross.jsonl the incremental CROSS fetch extends",
    )
    args = parser.parse_args(argv)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in FETCHERS]
    if unknown:
        parser.error(f"unknown sources: {unknown}")

    manifests = build_snapshot(
        args.out,
        sources=sources,
        cross_kwargs={"full": args.full_cross, "base_dir": args.cross_base},
        progress=lambda msg: print(msg, file=sys.stderr, flush=True),
    )
    print(json.dumps({s: m.to_dict() for s, m in manifests.items()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
