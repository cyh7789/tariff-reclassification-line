"""Deterministic tariff triage."""

from .duty import DutyRate
from .engine import triage
from .types import Bucket, Candidate, LineItem, Route, TriageResult

__all__ = [
    "Bucket",
    "Candidate",
    "DutyRate",
    "LineItem",
    "Route",
    "TriageResult",
    "triage",
]
