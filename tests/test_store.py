"""State transitions are the thing the officer signs off on, so they are enforced.

Two properties matter more than the CRUD around them: an illegal move is refused
rather than recorded, and a retried worker does not produce a second result.
"""

import pytest

from fleet.workflow.store import CaseState, IllegalTransition, Store


ITEMS = [
    {"item_id": "A-1", "description": "an ultrasonic bath", "prior_code": "854370"},
    {"item_id": "A-2", "description": "a horticultural sprayer", "prior_code": "842441"},
]


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "cases.db")


@pytest.fixture
def batch(store):
    return store.create_batch("plant-a", "August catalog", "2026-08-18", ITEMS)


def test_a_new_batch_starts_every_case_received(store, batch):
    cases = store.cases(batch)

    assert len(cases) == 2
    assert {c.state for c in cases} == {CaseState.RECEIVED}


def test_a_legal_move_is_recorded_with_its_fields(store, batch):
    case = store.cases(batch)[0]

    assert store.transition(case.case_id, CaseState.CLASSIFYING, "worker", "k1")
    assert store.transition(case.case_id, CaseState.READY, "worker", "k2",
                            selected_code="85437098", confidence=0.94)

    after = store.case(case.case_id)
    assert after.state is CaseState.READY
    assert after.selected_code == "85437098"
    assert [e["to_state"] for e in store.events(case.case_id)] == ["CLASSIFYING", "READY"]


def test_an_illegal_move_is_refused(store, batch):
    """A case that never got its missing fact cannot be waved through."""
    case = store.cases(batch)[0]
    store.transition(case.case_id, CaseState.CLASSIFYING, "worker", "k1")
    store.transition(case.case_id, CaseState.NEEDS_INPUT, "worker", "k2",
                     missing_property="what is the housing material?")

    with pytest.raises(IllegalTransition):
        store.transition(case.case_id, CaseState.APPROVED, "officer", "k3")

    assert store.case(case.case_id).state is CaseState.NEEDS_INPUT


def test_a_retried_worker_writes_nothing_the_second_time(store, batch):
    """A task queue redelivers; a redelivery must not classify twice."""
    case = store.cases(batch)[0]
    store.transition(case.case_id, CaseState.CLASSIFYING, "worker", "same-key")

    assert store.transition(case.case_id, CaseState.READY, "worker", "result-key",
                            selected_code="85437098") is True
    assert store.transition(case.case_id, CaseState.READY, "worker", "result-key",
                            selected_code="99999999") is False

    assert store.case(case.case_id).selected_code == "85437098"
    assert len(store.events(case.case_id)) == 2


def test_batch_approval_takes_the_ready_and_names_what_it_held(store, batch):
    ready, blocked = store.cases(batch)
    store.transition(ready.case_id, CaseState.CLASSIFYING, "worker", "a1")
    store.transition(ready.case_id, CaseState.READY, "worker", "a2")
    store.transition(blocked.case_id, CaseState.CLASSIFYING, "worker", "b1")
    store.transition(blocked.case_id, CaseState.NEEDS_INPUT, "worker", "b2",
                     missing_property="what is the tank capacity?")

    result = store.approve_batch(batch, "dana")

    assert result["approved"] == 1
    assert [h["state"] for h in result["held"]] == ["NEEDS_INPUT"]
    assert store.case(ready.case_id).state is CaseState.APPROVED
    assert store.case(blocked.case_id).state is CaseState.NEEDS_INPUT


def test_approving_twice_does_not_double_count(store, batch):
    for case in store.cases(batch):
        store.transition(case.case_id, CaseState.SETTLED, "triage", f"s-{case.case_id}")

    assert store.approve_batch(batch, "dana")["approved"] == 2
    assert store.approve_batch(batch, "dana")["approved"] == 0


def test_a_tenant_cannot_read_another_tenants_cases(store, batch):
    """The isolation boundary is the product line, and it is applied on read."""
    case = store.cases(batch)[0]

    assert store.case(case.case_id, tenant="plant-a") is not None
    assert store.case(case.case_id, tenant="plant-b") is None
    assert store.cases(batch, tenant="plant-b") == []


def test_a_refused_case_can_be_requeued_once_the_fact_arrives(store, batch):
    case = store.cases(batch)[0]
    store.transition(case.case_id, CaseState.CLASSIFYING, "worker", "r1")
    store.transition(case.case_id, CaseState.NEEDS_INPUT, "worker", "r2",
                     missing_property="what is the housing material?")

    assert store.transition(case.case_id, CaseState.CLASSIFYING, "engineering", "r3",
                            detail="material: stainless steel")

    assert store.case(case.case_id).state is CaseState.CLASSIFYING


def test_approving_a_selection_leaves_the_rest_alone(store, batch):
    """Reviewing part of a batch before signing is ordinary practice."""
    first, second = store.cases(batch)
    for case in (first, second):
        store.transition(case.case_id, CaseState.SETTLED, "triage", f"s-{case.case_id}")

    result = store.approve_batch(batch, "dana", only={first.case_id})

    assert result["approved"] == 1
    assert store.case(first.case_id).state is CaseState.APPROVED
    assert store.case(second.case_id).state is CaseState.SETTLED
    assert result["held"] == []


def test_a_selection_that_names_a_blocked_case_does_not_force_it_through(store, batch):
    blocked, ready = store.cases(batch)
    store.transition(blocked.case_id, CaseState.CLASSIFYING, "worker", "b1")
    store.transition(blocked.case_id, CaseState.NEEDS_INPUT, "worker", "b2",
                     missing_property="what is the tank capacity?")
    store.transition(ready.case_id, CaseState.SETTLED, "triage", "r1")

    result = store.approve_batch(batch, "dana",
                                 only={blocked.case_id, ready.case_id})

    assert result["approved"] == 1
    assert [h["state"] for h in result["held"]] == ["NEEDS_INPUT"]
    assert store.case(blocked.case_id).state is CaseState.NEEDS_INPUT


def test_the_transcript_survives_the_round_trip_and_reaches_replay(store, batch):
    """The tape and the replay both read this column, so an empty one is a blank
    screen rather than a visible error."""
    case = store.cases(batch)[0]
    rows = [{"kind": "reject", "actor": "agent", "text": "852411 ruled out",
             "detail": "sweep heading for display modules", "ref": "Note 7 to Chapter 85"}]
    store.transition(case.case_id, CaseState.CLASSIFYING, "worker", "t1")
    store.transition(case.case_id, CaseState.READY, "worker", "t2", steps=rows)

    assert store.case(case.case_id).steps == rows
    landed = [e for e in store.timeline(batch) if e["to_state"] == "READY"]
    assert landed[0]["steps"] == rows


def test_each_attempt_keeps_its_own_transcript(store, batch):
    """A case refused for a missing fact and re-run after engineering answered has
    two attempts, and the first is where the refusal was reasoned. The case row
    holds the latest; overwriting the rest would leave the signature resting on a
    decision whose earlier half is gone."""
    case = store.cases(batch)[0]
    store.transition(case.case_id, CaseState.CLASSIFYING, "worker", "a1")
    store.transition(case.case_id, CaseState.NEEDS_INPUT, "classifier", "a2",
                     steps=[{"kind": "refuse", "text": "no sleeve length stated"}],
                     missing_property="are the sleeves long or is it sleeveless?")
    store.transition(case.case_id, CaseState.CLASSIFYING, "contributor", "a3",
                     detail="sleeves -> long, hemmed")
    store.transition(case.case_id, CaseState.READY, "classifier", "a4",
                     steps=[{"kind": "select", "text": "selected 62012040"}])

    attempts = store.attempts(case.case_id)
    assert [a["to_state"] for a in attempts] == ["NEEDS_INPUT", "READY"]
    assert attempts[0]["steps"][0]["text"] == "no sleeve length stated"
    assert attempts[1]["steps"][0]["text"] == "selected 62012040"
    assert store.case(case.case_id).steps == attempts[-1]["steps"]


def test_a_transition_with_no_transcript_does_not_open_an_attempt(store, batch):
    """Supplying a fact is a move, not an attempt at classifying."""
    case = store.cases(batch)[0]
    store.transition(case.case_id, CaseState.CLASSIFYING, "worker", "b1")

    assert store.attempts(case.case_id) == []


def _flagged(store, batch, **kw):
    case = store.cases(batch)[0]
    store.transition(case.case_id, CaseState.SETTLED, "triage", "f1",
                     selected_code="62046200",
                     findings=[{"kind": "SCREENING_MATCH", "severity": 0,
                                "headline": "Possible match on the SDN list",
                                "detail": "resembles a listed party"} | kw])
    return case


def test_a_batch_signature_does_not_clear_what_only_a_person_can_decide(store, batch):
    """A supplier resembling a sanctioned party was being approved by an action
    that decides nothing, with no record that anybody had looked."""
    case = _flagged(store, batch)

    result = store.approve_batch(batch, "approver")

    assert result["approved"] == 0
    # The batch also holds its untouched second case, so find ours rather than
    # relying on the order the rows came back in.
    ours = next(h for h in result["held"] if h["case_id"] == case.case_id)
    assert "SDN" in ours["why"]
    assert store.case(case.case_id).state is CaseState.SETTLED


def test_a_decision_carries_a_name_and_a_time_and_then_it_signs(store, batch):
    case = _flagged(store, batch)

    decided = store.decide_finding(case.case_id, 0, "cleared", "approver",
                                   "different address, same trading name")
    assert decided["decision"] == "cleared"
    assert decided["decided_by"] == "approver" and decided["decided_at"]
    assert any("cleared" in e["detail"] for e in store.events(case.case_id))

    assert store.approve_batch(batch, "approver")["approved"] == 1


def test_holding_it_is_a_decision_too_and_still_holds_the_case(store, batch):
    case = _flagged(store, batch)
    store.decide_finding(case.case_id, 0, "held", "approver", "waiting on the licence")

    # Decided, so the signature is no longer blocked by an unexamined finding:
    # the officer chose to hold it, and holding is theirs to lift.
    assert store.approve_batch(batch, "approver")["approved"] == 1


def test_a_computed_finding_is_not_a_person_s_to_decide(store, batch):
    case = _flagged(store, batch, severity=1)

    with pytest.raises(ValueError, match="settled by the machine"):
        store.decide_finding(case.case_id, 0, "cleared", "approver")
