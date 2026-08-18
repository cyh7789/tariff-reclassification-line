"""The round trip, as one card: what was asked, who answered, what it changed.

A case that went out for a fact and came back has two transcripts, and reading
them side by side is work the officer should not have to do. What matters is the
difference between them and why it exists, so this states it: the agent refused,
a named person answered, the agent decided.

This is the part of the product that cannot be faked by running faster. The wait
is real, it spans whatever it spans, and the case survives it with its history
intact. So the elapsed time is on the card rather than hidden: a gap of days is
the claim, not an embarrassment.

Pure, and given data rather than a store, because the interesting cases are the
ones that are awkward to reach through the API: three attempts, a fact that
arrived while nobody was looking, a question nobody answered yet.
"""

from __future__ import annotations

from datetime import datetime


def _when(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat((stamp or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def elapsed(start: str, end: str) -> str:
    """How long the question was outstanding, in the coarsest honest unit."""
    began, ended = _when(start), _when(end)
    if began is None or ended is None:
        return ""
    seconds = int((ended - began).total_seconds())
    if seconds < 0:
        return ""
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count > 1 else ''}"
    return "under a minute"


def card(attempts: list[dict], facts: list[dict], selected_code: str | None) -> dict | None:
    """One card per answered question, or None when nothing went out and came back.

    Keyed on the fact rather than on the attempt count: an attempt that failed
    verification and was re-run is a retry, not a round trip, and calling it one
    would credit the system with cross-department work it never did.
    """
    if not facts:
        return None
    fact = facts[0]
    refusal = next((a for a in attempts if a["to_state"] == "NEEDS_INPUT"), None)
    after = next((a for a in reversed(attempts) if a["to_state"] != "NEEDS_INPUT"), None)
    if refusal is None:
        return None
    return {
        "asked": fact.get("property") or "a fact the description did not state",
        "answered": fact.get("value", ""),
        "answered_by": fact.get("supplied_by", ""),
        "asked_at": refusal["at"],
        "answered_at": fact.get("at", ""),
        "waited": elapsed(refusal["at"], fact.get("at", "")),
        # None while the re-run is still in flight, which is a state the screen
        # has to be able to show: the fact is in, the answer is not yet.
        "outcome": (after or {}).get("to_state"),
        "selected_code": selected_code if after else None,
    }
