"""Route tariff line items using a trusted local snapshot."""

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Sequence

from fleet.sync.gate import assert_healthy

from .duty import resolve
from .types import Bucket, Candidate, LineItem, Route, TriageResult


def triage(items: Sequence[LineItem], snapshot_dir: Path) -> list[TriageResult]:
    """Classify items before any agent is invoked."""
    assert_healthy(snapshot_dir, sources=("hts", "correlation"))
    snapshot_id = _load_snapshot_id(snapshot_dir)
    hts_rows = _load_jsonl(snapshot_dir / "hts.jsonl")
    # Only 6844 of the 14957 distinct 8-digit codes in 2026HTSRev16 get a row of
    # their own; the rest exist solely as the prefix of their 10-digit lines.
    # Requiring an exact 8-digit row would report 54% of a live catalog as withdrawn.
    current_hts8 = {
        str(row["htsno"])[:8]
        for row in hts_rows
        if row.get("htsno") and len(str(row["htsno"])) >= 8
    }
    correlations = _load_correlations(snapshot_dir / "correlation.csv")

    return [
        _triage_item(item, snapshot_id, hts_rows, current_hts8, correlations)
        for item in items
    ]


def _triage_item(
    item: LineItem,
    snapshot_id: str,
    hts_rows: Sequence[dict],
    current_hts8: set[str],
    correlations: dict[str, tuple[Candidate, ...]],
) -> TriageResult:
    hts8 = item.hs_code[:8]
    hs6 = item.hs_code[:6]
    candidates = correlations.get(hs6, ())

    if hts8 in current_hts8:
        split_source = len(candidates) > 1 or any(
            candidate.is_ex for candidate in candidates
        )
        if split_source:
            return TriageResult(
                item_id=item.item_id,
                bucket=Bucket.SCOPE_REVIEW,
                route=Route.AGENT,
                reason="current code may have reduced scope; requires review",
                candidates=candidates,
                selected_code=None,
                current_duty=resolve(item.hs_code, hts_rows),
                prior_duty=None,
                snapshot_id=snapshot_id,
            )
        return TriageResult(
            item_id=item.item_id,
            bucket=Bucket.SURVIVED,
            route=Route.DETERMINISTIC,
            reason="code unchanged in current revision",
            candidates=(),
            selected_code=None,
            current_duty=resolve(item.hs_code, hts_rows),
            prior_duty=None,
            snapshot_id=snapshot_id,
        )

    if not candidates:
        return TriageResult(
            item_id=item.item_id,
            bucket=Bucket.DEAD_CODE,
            route=Route.AGENT,
            reason="no correlation entry; requires reclassification from first principles",
            candidates=(),
            selected_code=None,
            current_duty=None,
            prior_duty=None,
            snapshot_id=snapshot_id,
        )

    deterministic = len(candidates) == 1 and not candidates[0].is_ex
    return TriageResult(
        item_id=item.item_id,
        bucket=Bucket.DEAD_CODE,
        route=Route.DETERMINISTIC if deterministic else Route.AGENT,
        reason=(
            "one-to-one correlation, resolved by table lookup"
            if deterministic
            else "correlation requires product-specific classification judgment"
        ),
        candidates=candidates,
        selected_code=candidates[0].hs_code if deterministic else None,
        current_duty=None,
        prior_duty=None,
        snapshot_id=snapshot_id,
    )


def _load_snapshot_id(snapshot_dir: Path) -> str:
    with (snapshot_dir / "SNAPSHOT.json").open(encoding="utf-8") as handle:
        return str(json.load(handle)["snapshot_id"])


def _load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _load_correlations(path: Path) -> dict[str, tuple[Candidate, ...]]:
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            candidate = Candidate(
                hs_code=row["hs2022"],
                is_ex=row["is_ex"] == "1",
                relationship=row["unsd_relationship"],
            )
            if candidate not in grouped[row["hs2017"]]:
                grouped[row["hs2017"]].append(candidate)
    return {source: tuple(values) for source, values in grouped.items()}
