"""The card claims cross-department work happened, so it has to be picky."""

from fleet.workflow.roundtrip import card, elapsed


def attempt(state, at):
    return {"to_state": state, "at": at, "actor": "classifier", "steps": []}


def fact(at, prop="sleeve construction", value="long, hemmed sleeves"):
    return {"property": prop, "value": value, "supplied_by": "engineering", "at": at}


REFUSED = attempt("NEEDS_INPUT", "2026-08-14T09:00:00+00:00")
DECIDED = attempt("READY", "2026-08-16T11:30:00+00:00")
ANSWERED = fact("2026-08-16T11:00:00+00:00")


def test_a_completed_round_trip_says_what_changed_it():
    c = card([REFUSED, DECIDED], [ANSWERED], "62012040")
    assert c["asked"] == "sleeve construction"
    assert c["answered_by"] == "engineering"
    assert c["waited"] == "2 days"
    assert c["outcome"] == "READY"
    assert c["selected_code"] == "62012040"


def test_no_fact_means_no_round_trip():
    assert card([REFUSED], [], None) is None


def test_a_rerun_after_a_failed_check_is_not_a_round_trip():
    """Nobody was asked anything, so nothing came back from another department."""
    assert card([attempt("VERIFY_FAILED", "2026-08-14T09:00:00+00:00"),
                 DECIDED], [], "62012040") is None


def test_the_answer_can_be_in_before_the_rerun_finishes():
    c = card([REFUSED], [ANSWERED], "62012040")
    assert c["outcome"] is None
    assert c["selected_code"] is None, "no code has been chosen on this evidence yet"
    assert c["answered"] == "long, hemmed sleeves"


def test_the_wait_is_reported_in_the_coarsest_honest_unit():
    assert elapsed("2026-08-14T09:00:00+00:00", "2026-08-14T09:00:30+00:00") == "under a minute"
    assert elapsed("2026-08-14T09:00:00+00:00", "2026-08-14T09:40:00+00:00") == "40 minutes"
    assert elapsed("2026-08-14T09:00:00+00:00", "2026-08-14T12:00:00+00:00") == "3 hours"
    assert elapsed("2026-08-14T09:00:00+00:00", "2026-08-15T09:00:00+00:00") == "1 day"


def test_a_wait_that_cannot_be_computed_is_left_blank_not_guessed():
    assert elapsed("not a date", "2026-08-14T09:00:00+00:00") == ""
    assert elapsed("2026-08-16T09:00:00+00:00", "2026-08-14T09:00:00+00:00") == ""


def test_a_question_with_no_property_recorded_still_reads_as_a_question():
    c = card([REFUSED], [fact("2026-08-16T11:00:00+00:00", prop="")], None)
    assert c["asked"] == "a fact the description did not state"
