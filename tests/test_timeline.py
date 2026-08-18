"""The band claims weeks passed, so its arithmetic has to be checkable."""

from fleet.workflow.timeline import band, spans

NOW = "2026-08-28T09:00:00+00:00"


def ev(to_state, at):
    return {"to_state": to_state, "at": at}


ROUND_TRIP = [
    ev("RECEIVED", "2026-08-18T09:00:00+00:00"),
    ev("CLASSIFYING", "2026-08-18T09:02:00+00:00"),
    ev("NEEDS_INPUT", "2026-08-18T09:05:00+00:00"),
    ev("CLASSIFYING", "2026-08-25T14:05:00+00:00"),
    ev("READY", "2026-08-25T14:08:00+00:00"),
    ev("APPROVED", "2026-08-25T16:00:00+00:00"),
]


def test_the_wait_and_the_work_are_different_spans():
    out = spans(ROUND_TRIP, NOW)

    waiting = next(s for s in out if s.state == "NEEDS_INPUT")
    assert waiting.holder == "contributor"
    assert not waiting.working
    assert waiting.seconds == 7 * 86400 + 5 * 3600, "18th 09:05 to 25th 14:05"


def test_the_agent_ran_twice_and_both_runs_are_kept():
    out = [s for s in spans(ROUND_TRIP, NOW) if s.state == "CLASSIFYING"]

    assert len(out) == 2, "collapsing these would erase the round trip"
    assert [s.seconds for s in out] == [180, 180]


def test_a_case_still_sitting_somewhere_is_measured_against_now():
    out = spans([ev("RECEIVED", "2026-08-18T09:00:00+00:00"),
                 ev("NEEDS_INPUT", "2026-08-18T09:05:00+00:00")], NOW)

    open_span = out[-1]
    assert open_span.end is None, "it has not left this state"
    assert open_span.seconds > 9 * 86400


def test_a_signed_case_stops_accruing_time():
    """APPROVED is where the case's life ends. Letting it run to now would grow
    the batch's waiting total every time somebody refreshed the page."""
    out = spans(ROUND_TRIP, NOW)

    assert out[-1].state == "APPROVED"
    assert out[-1].seconds == 0


def test_the_totals_separate_what_it_cost_from_what_it_removed():
    out = band([{"item_id": "SKU-1013", "events": ROUND_TRIP}], NOW)

    assert out["working"] == 120 + 180 + 180, "RECEIVED plus two agent runs"
    assert out["waiting"] == 7 * 86400 + 5 * 3600 + 6720, "the refusal plus READY's 1h52m"
    assert out["from"] == "2026-08-18T09:00:00+00:00"


def test_a_batch_nobody_has_touched_yet_is_an_empty_band():
    out = band([{"item_id": "SKU-1", "events": []}], NOW)

    assert out["lanes"] == []
    assert out["working"] == out["waiting"] == 0


def test_an_unparseable_timestamp_is_dropped_rather_than_guessed():
    out = spans([ev("RECEIVED", "whenever"), ev("CLASSIFYING", "2026-08-18T09:02:00+00:00")], NOW)

    assert [s.state for s in out] == ["CLASSIFYING"]


def test_a_case_stuck_mid_run_is_not_counted_as_agent_work():
    """Measured on the real database: a batch reported 17 hours of agent work,
    all of it one case left in CLASSIFYING by a worker that died. An open
    machine span is either in flight or stranded and the band cannot tell which,
    so it does not get to claim the time as work."""
    out = band([{"item_id": "SKU-1", "events": [
        ev("RECEIVED", "2026-08-18T09:00:00+00:00"),
        ev("CLASSIFYING", "2026-08-18T09:02:00+00:00")]}], NOW)

    assert out["working"] == 120, "only the closed RECEIVED span was real"
    assert out["lanes"][0]["spans"][-1]["open"] is True


def test_a_case_still_waiting_on_a_person_does_count(): 
    """The other side of the same asymmetry, and the reason for it: nine days
    waiting on engineering is the claim, not an unfinished measurement."""
    out = band([{"item_id": "SKU-2", "events": [
        ev("RECEIVED", "2026-08-18T09:00:00+00:00"),
        ev("NEEDS_INPUT", "2026-08-18T09:02:00+00:00")]}], NOW)

    assert out["waiting"] > 9 * 86400
