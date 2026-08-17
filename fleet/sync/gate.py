"""Snapshot health gate (contract section 2).

Track B calls `assert_healthy` before reading a snapshot. There is no partial
mode: either every requested source passes every check, or the caller halts.

The checks exist because of three failure modes seen for real while probing the
sources (see reference/D1-VERIFY-data.md):

* government endpoints answer 302, so every fetch follows redirects;
* a wrong filename returns HTTP 200 with a zero-byte body instead of 404, and
  an empty screening list means everything passes screening, so the size and
  row-count floors are the real check, never the status code;
* CROSS search returns ruling numbers upper-case while the detail endpoint
  returns them lower-case, so the sync layer normalizes to upper-case on write.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from fleet.sync.manifest import (
    ALL_SOURCES,
    SNAPSHOT_FILE,
    Manifest,
    data_path,
    manifest_path,
    sha256_file,
)

MAX_STALENESS_DAYS = 30

__all__ = [
    "ALL_SOURCES",
    "DataSourceUnhealthy",
    "MAX_STALENESS_DAYS",
    "Manifest",
    "assert_healthy",
    "load_manifest",
]


class DataSourceUnhealthy(Exception):
    """Raised when a snapshot cannot be trusted. Callers must halt, never degrade."""


def load_manifest(snapshot_dir: Path, source: str) -> Manifest:
    path = manifest_path(snapshot_dir, source)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataSourceUnhealthy(f"{source}: manifest missing at {path}") from exc
    except json.JSONDecodeError as exc:
        raise DataSourceUnhealthy(f"{source}: manifest is not valid JSON: {exc}") from exc
    try:
        return Manifest.from_dict(raw)
    except (TypeError, ValueError) as exc:
        raise DataSourceUnhealthy(f"{source}: unreadable manifest: {exc}") from exc


def assert_healthy(snapshot_dir: Path, sources: Sequence[str] = ALL_SOURCES) -> None:
    snapshot_dir = Path(snapshot_dir)
    _assert_snapshot_complete(snapshot_dir)
    for source in sources:
        _assert_source_healthy(snapshot_dir, source)


def _assert_snapshot_complete(snapshot_dir: Path) -> None:
    path = snapshot_dir / SNAPSHOT_FILE
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataSourceUnhealthy(
            f"{SNAPSHOT_FILE} missing at {path}; the snapshot is incomplete"
        ) from exc
    except json.JSONDecodeError as exc:
        raise DataSourceUnhealthy(f"{SNAPSHOT_FILE} is not valid JSON: {exc}") from exc
    status = marker.get("status")
    if status != "ok":
        raise DataSourceUnhealthy(f"{SNAPSHOT_FILE} status is {status!r}, expected 'ok'")


def _assert_source_healthy(snapshot_dir: Path, source: str) -> None:
    manifest = load_manifest(snapshot_dir, source)
    if manifest.status != "ok":
        raise DataSourceUnhealthy(
            f"{source}: manifest status is {manifest.status!r}, expected 'ok'"
        )

    if manifest.row_count < manifest.min_rows:
        raise DataSourceUnhealthy(
            f"{source}: row_count {manifest.row_count} is below the floor "
            f"{manifest.min_rows}"
        )
    if manifest.bytes < manifest.min_bytes:
        raise DataSourceUnhealthy(
            f"{source}: {manifest.bytes} bytes is below the floor {manifest.min_bytes}"
        )

    path = data_path(snapshot_dir, source)
    try:
        on_disk = sha256_file(path)
    except FileNotFoundError as exc:
        raise DataSourceUnhealthy(f"{source}: data file missing at {path}") from exc
    if on_disk != manifest.sha256:
        raise DataSourceUnhealthy(
            f"{source}: sha256 mismatch, manifest says {manifest.sha256} "
            f"but {path.name} hashes to {on_disk}"
        )

    if manifest.staleness_days > MAX_STALENESS_DAYS:
        raise DataSourceUnhealthy(
            f"{source}: {manifest.staleness_days} days stale, limit is "
            f"{MAX_STALENESS_DAYS}"
        )
