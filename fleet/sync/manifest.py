"""Manifest record shared by every source (contract section 1.1).

One manifest sits next to each data file in a snapshot directory. The floors
(`min_rows`, `min_bytes`) travel inside the manifest instead of living in the
gate, so a snapshot stays checkable after the code that produced it changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ALL_SOURCES: tuple[str, ...] = ("hts", "cross", "csl", "correlation")

DATA_FILES: dict[str, str] = {
    "hts": "hts.jsonl",
    "cross": "cross.jsonl",
    "csl": "csl.jsonl",
    "correlation": "correlation.csv",
}

SNAPSHOT_FILE = "SNAPSHOT.json"

_READ_CHUNK = 1 << 20


@dataclass(frozen=True)
class Manifest:
    source: str
    url: str
    fetched_at: str
    revision: str | None
    row_count: int
    bytes: int
    sha256: str
    min_rows: int
    min_bytes: int
    status: str
    staleness_days: int

    @property
    def data_filename(self) -> str:
        return DATA_FILES[self.source]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Manifest":
        fields = {f: raw.get(f) for f in cls.__dataclass_fields__}
        missing = [k for k, v in fields.items() if v is None and k != "revision"]
        if missing:
            raise ValueError(f"manifest is missing fields: {sorted(missing)}")
        return cls(**fields)


def manifest_path(snapshot_dir: Path, source: str) -> Path:
    return Path(snapshot_dir) / f"{source}.manifest.json"


def data_path(snapshot_dir: Path, source: str) -> Path:
    return Path(snapshot_dir) / DATA_FILES[source]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(moment: datetime) -> str:
    """RFC3339 with a trailing Z, matching the contract's examples."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def staleness_days(last_modified: datetime | None, fetched_at: datetime) -> int:
    """Days between the source's own Last-Modified and this fetch.

    A source that sends no Last-Modified is measured against `fetched_at`,
    which is zero by construction; the contract accepts that and the row and
    byte floors are what actually catch a stale or truncated payload.
    """
    if last_modified is None:
        return 0
    delta = fetched_at - last_modified
    return max(0, delta.days)


def build_manifest(
    *,
    source: str,
    url: str,
    snapshot_dir: Path,
    fetched_at: datetime,
    revision: str | None,
    row_count: int,
    min_rows: int,
    min_bytes: int,
    last_modified: datetime | None = None,
) -> Manifest:
    """Measure the written data file and describe it."""
    path = data_path(snapshot_dir, source)
    return Manifest(
        source=source,
        url=url,
        fetched_at=iso_utc(fetched_at),
        revision=revision,
        row_count=row_count,
        bytes=path.stat().st_size,
        sha256=sha256_file(path),
        min_rows=min_rows,
        min_bytes=min_bytes,
        status="ok",
        staleness_days=staleness_days(last_modified, fetched_at),
    )


def write_manifest(snapshot_dir: Path, manifest: Manifest) -> Path:
    path = manifest_path(snapshot_dir, manifest.source)
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path
