"""A batch laid out on real time: what was working, and what was waiting.

The track asks for context maintained `across weeks of asynchronous operations`,
and the honest way to show that is a clock. A batch's own run takes minutes; the
weeks come from the cases that stop, sit on somebody's desk, and are picked up
again days later with their history intact. On one axis those two look completely
different, and that difference is the claim.

So every case becomes a row of spans, and every span says who held it. Time spent
inside the machine and time spent waiting for a person are not the same kind of
time: one is what the product costs, the other is what it removes. Drawing them
in the same ink would hide the only comparison worth making.

Nothing here invents a timestamp. A span with no end is a case that is still
where it is, measured against now, and it shrinks or grows for real reasons only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

#: Who is holding a case while it sits in each state. `machine` is the system
#: doing the work; a role name is the system waiting on that person. This is the
#: same vocabulary the flow diagram and the table's "With" column already use,
#: because three names for one idea is how a screen stops being readable.
HOLDER = {
    "RECEIVED": "machine",
    "CLASSIFYING": "machine",
    "SETTLED": "approver",
    "READY": "approver",
    "NEEDS_INPUT": "contributor",
    "VERIFY_FAILED": "approver",
    "BLOCKED": "operator",
    "APPROVED": "done",
}


@dataclass(frozen=True)
class Span:
    state: str
    holder: str
    start: str
    #: None while the case is still in this state. The screen draws it up to now.
    end: str | None
    seconds: int

    @property
    def open(self) -> bool:
        """Still in this state. The end is now, and now keeps moving."""
        return self.end is None

    @property
    def working(self) -> bool:
        """Time the machine can be said to have spent on the case.

        An open machine span does not qualify. It is either a run in flight or a
        case a dead worker left behind, and nothing in the event log separates
        the two: measured on the real database, one stranded case alone reported
        seventeen hours of agent work. Person spans are counted open, because a
        case that has been waiting on engineering for nine days is the claim
        rather than an unfinished measurement.
        """
        return self.holder == "machine" and not self.open


def _at(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat((stamp or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def spans(events: list[dict], now: str | None = None) -> list[Span]:
    """One span per stretch the case spent in a state, oldest first.

    Built from the transitions rather than from the case's current state: a case
    that went out for a fact and came back has been in CLASSIFYING twice, and
    collapsing those into one would erase the round trip that is the point.
    """
    if not events:
        return []
    end = _at(now) if now else datetime.now(timezone.utc)
    out: list[Span] = []
    for index, event in enumerate(events):
        began = _at(event["at"])
        if began is None:
            continue
        state = event["to_state"]
        if index + 1 < len(events):
            finished, closes = _at(events[index + 1]["at"]), events[index + 1]["at"]
        else:
            finished, closes = (end, None) if state != "APPROVED" else (began, None)
        if finished is None:
            continue
        out.append(Span(state, HOLDER.get(state, "machine"), event["at"], closes,
                        max(0, int((finished - began).total_seconds()))))
    return out


def band(rows: list[dict], now: str | None = None) -> dict:
    """The whole batch on one axis, plus the totals the axis is there to show.

    `rows` is `[{"item_id": ..., "events": [...]}]`. The window runs from the
    first event to now, so a batch that finished in eight minutes and a batch
    still waiting on engineering after nine days are drawn to the same scale and
    read as the different things they are.
    """
    lanes = []
    for row in rows:
        lane = spans(row.get("events") or [], now)
        if lane:
            lanes.append({"item_id": row.get("item_id", "?"),
                          "case_id": row.get("case_id", ""),
                          "spans": [s.__dict__ | {"working": s.working, "open": s.open}
                                    for s in lane]})
    if not lanes:
        return {"from": None, "to": now, "lanes": [], "working": 0, "waiting": 0}
    starts = [lane["spans"][0]["start"] for lane in lanes]
    working = sum(s["seconds"] for lane in lanes for s in lane["spans"] if s["working"])
    # Time nobody was working and the case was not finished: what the product is
    # for, stated as a number rather than left to be eyeballed off the bars.
    waiting = sum(s["seconds"] for lane in lanes for s in lane["spans"]
                  if not s["working"] and s["state"] != "APPROVED")
    return {"from": min(starts), "to": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lanes": lanes, "working": working, "waiting": waiting}
