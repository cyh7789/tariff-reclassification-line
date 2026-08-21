"""The card claims cross-department work happened, so it has to be picky."""

from fleet.workflow.roundtrip import batch, card, elapsed, outstanding


def attempt(state, at):
    return {"to_state": state, "at": at, "actor": "classifier", "steps": []}


def fact(at, prop="sleeve construction", value="long, hemmed sleeves"):
    return {"property": prop, "value": value, "supplied_by": "engineering", "at": at}


REFUSED = attempt("NEEDS_INPUT", "2026-08-14T09:00:00+00:00")
DECIDED = attempt("READY", "2026-08-16T11:30:00+00:00")
ANSWERED = fact("2026-08-16T11:00:00+00:00")
#: Fourteen days after the refusal, so an unanswered question has a real wait.
NOW = "2026-08-28T09:00:00+00:00"


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


OPEN_CASE = {"case_id": "C-9", "item_id": "SKU-1013", "state": "NEEDS_INPUT",
             "missing_property": "what is the water resistance rating?",
             "ask_department": "engineering", "selected_code": None}
DONE_CASE = {"case_id": "C-1", "item_id": "SKU-1013b", "state": "READY",
             "missing_property": "", "ask_department": "",
             "selected_code": "62012040"}


def test_a_question_nobody_has_answered_is_still_shown():
    """Most of what an officer waits on is still out. A screen that only drew
    the finished ones would show a system that never waits."""
    out = outstanding(OPEN_CASE, [REFUSED], NOW)

    assert out["asked_of"] == "engineering"
    assert out["open"] is True
    assert out["waiting"] == "14 days"


def test_the_asking_time_comes_from_the_events_not_the_transcripts():
    """A transcript is written per run and the older batches predate that table;
    the transition is append-only and is always there. Reading the attempts left
    every real open question invisible on the batches that already exist."""
    assert outstanding(OPEN_CASE, [], NOW) is None
    assert outstanding(OPEN_CASE, [REFUSED], NOW)["waiting"] == "14 days"


def test_a_case_that_is_not_waiting_has_no_open_question():
    assert outstanding(DONE_CASE, [REFUSED, DECIDED], NOW) is None


def test_the_batch_puts_the_open_questions_first():
    rows = [{"case": DONE_CASE, "facts": [ANSWERED], "attempts": [REFUSED, DECIDED],
             "events": [REFUSED, DECIDED]},
            {"case": OPEN_CASE, "facts": [], "attempts": [], "events": [REFUSED]}]
    out = batch(rows, NOW)

    assert [r["open"] for r in out] == [True, False], "work before evidence"
    assert out[0]["item_id"] == "SKU-1013"
    assert out[1]["selected_code"] == "62012040"


def test_a_case_that_never_asked_anything_is_not_in_the_list():
    quiet = {"case_id": "C-2", "item_id": "SKU-1002", "state": "SETTLED",
             "selected_code": "732690"}
    assert batch([{"case": quiet, "facts": [], "attempts": [], "events": []}], NOW) == []


def test_it_works_without_being_told_what_time_it_is():
    """Every other test passes `now`, so the default path was never executed and
    a missing import for it shipped."""
    out = outstanding(OPEN_CASE, [REFUSED])

    assert out["waiting"], "an open question always has a wait"


def test_a_worker_crash_is_marked_failed_not_dressed_as_a_question():
    case = {"case_id": "C-err", "item_id": "X-9", "state": "NEEDS_INPUT",
            "missing_property": "the classifier could not complete; a person should look",
            "ask_department": "compliance"}
    events = [{"to_state": "NEEDS_INPUT", "at": "2026-08-20T09:00:00+00:00",
               "idempotency_key": "error:C-err:1"}]
    row = outstanding(case, events, now="2026-08-21T09:00:00+00:00")
    assert row["failed"] is True

    asked = [{"to_state": "NEEDS_INPUT", "at": "2026-08-20T09:00:00+00:00",
              "idempotency_key": "needs:C-ok:1"}]
    row = outstanding(case | {"case_id": "C-ok"}, asked, now="2026-08-21T09:00:00+00:00")
    assert row["failed"] is False
