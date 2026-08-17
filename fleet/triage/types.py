"""Frozen public types for tariff triage."""

from dataclasses import dataclass
from enum import StrEnum

from .duty import DutyRate


class Bucket(StrEnum):
    SURVIVED = "SURVIVED"
    DEAD_CODE = "DEAD_CODE"
    SCOPE_REVIEW = "SCOPE_REVIEW"


class Route(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    AGENT = "AGENT"


@dataclass(frozen=True)
class LineItem:
    item_id: str
    description: str
    hs_code: str
    product_line: str


@dataclass(frozen=True)
class Candidate:
    hs_code: str
    is_ex: bool
    relationship: str


@dataclass(frozen=True)
class TriageResult:
    item_id: str
    bucket: Bucket
    route: Route
    reason: str
    candidates: tuple[Candidate, ...]
    selected_code: str | None
    current_duty: DutyRate | None
    prior_duty: DutyRate | None
    snapshot_id: str
