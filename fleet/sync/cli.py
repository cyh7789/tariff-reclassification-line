"""Shared command-line plumbing for the four fetchers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fleet.sync.manifest import Manifest


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="snapshot directory to write into, e.g. data/snapshots/2026-08-18",
    )
    return parser


def report(manifest: Manifest) -> None:
    print(json.dumps(manifest.to_dict(), indent=2))
