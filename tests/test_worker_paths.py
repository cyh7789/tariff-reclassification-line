"""What the worker does at each exit, driven through the real chain.

The model is replaced; nothing else is. These tests exist because two claims in
the spec turned out to be about behaviour nothing implemented, and the only way
to tell the difference is to run the path and read the events it wrote.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from fleet.workflow.store import CaseState, Store
from fleet.workflow.worker import Worker

SNAPSHOT = Path(__file__).parent.parent / "data" / "snapshots" / "2026-08-18"
pytestmark = pytest.mark.skipif(not SNAPSHOT.exists(), reason="needs the live snapshot")


@pytest.fixture
def running(tmp_path, make_store):
    store = make_store(tmp_path)
    worker = Worker(store, SNAPSHOT)
    batch = store.create_batch("plant-a", "paths", "2026-08-18", [
        {"item_id": "X", "description": "a men's woven jacket", "prior_code": "620111"}])
    case = store.cases(batch)[0]
    store.transition(case.case_id, CaseState.CLASSIFYING, "worker", "start")
    return store, worker, case


def answer(**over):
    base = {"status": "CLASSIFIED", "selected_code": "6201204011",
            "selected_code_8": "62012040", "confidence": 0.95, "reasoning": "",
            "citations": [{"kind": "tariff_line", "ref": "6201204011"}],
            "rejected": [], "tool_calls": [], "tool_call_count": 0, "seconds": 1.0}
    return base | over


def run_with(worker, case, result):
    with patch.object(type(worker.runner), "classify",
                      lambda self, item, on_event=None: dict(result)):
        worker.run_case(case.case_id)


def test_a_citation_that_does_not_resolve_stops_the_case_and_waits_for_a_person(running):
    """The spec claimed a retry here. Nothing implemented one, and nothing should:
    the same data re-read produces the same missing ruling, at the price of
    another model call. It stops, and a person decides whether to run it again."""
    store, worker, case = running

    run_with(worker, case, answer(citations=[{"kind": "ruling", "ref": "N000000"}]))

    assert [e["to_state"] for e in store.events(case.case_id)] == \
        ["CLASSIFYING", "VERIFY_FAILED"]
    assert len(store.attempts(case.case_id)) == 1
    assert "N000000" in store.case(case.case_id).verify_reason


def test_a_refusal_names_the_property_and_the_department(running):
    store, worker, case = running

    run_with(worker, case, answer(status="NEEDS_INPUT", selected_code=None,
                                  selected_code_8=None, citations=[],
                                  missing_property="are the sleeves long or is it sleeveless?",
                                  ask_department="engineering"))

    settled = store.case(case.case_id)
    assert settled.state is CaseState.NEEDS_INPUT
    assert "sleeveless" in settled.missing_property
    assert settled.ask_department == "engineering"


def test_a_clean_classification_carries_its_compliance_findings(running):
    """The duty on 62012040 is 49.7¢/kg + 19.7%, so with no weight on the entry
    the case reaches a person with the part that is settled and the part that is
    not, rather than with a blank."""
    store, worker, case = running

    run_with(worker, case, answer())

    settled = store.case(case.case_id)
    assert settled.state is CaseState.READY
    assert settled.selected_code == "6201204011"
    kinds = {f["kind"] for f in settled.findings}
    assert "DUTY_NOT_COMPUTABLE" in kinds


def test_a_supplied_fact_survives_a_restart_that_carried_no_arguments(running):
    """Engineering answers once. Every later run of the case has to see it.

    It used to arrive as an argument to the endpoint that triggered the re-run,
    so a restart after a crash, or a re-run after a failed citation check, showed
    the agent the original description and asked the same question again.
    """
    store, worker, case = running
    store.transition(case.case_id, CaseState.NEEDS_INPUT, "classifier", "r1",
                     missing_property="are the sleeves long or is it sleeveless?",
                     ask_department="engineering")
    store.add_fact(case.case_id, "sleeves", "long, hemmed sleeves", "contributor")
    store.transition(case.case_id, CaseState.CLASSIFYING, "contributor", "r2")

    seen = {}

    def capture(self, item, on_event=None):
        seen["description"] = item.description
        return answer()

    with patch.object(type(worker.runner), "classify", capture):
        worker.run_case(case.case_id)          # no fact passed in, as a restart would

    assert "long, hemmed sleeves" in seen["description"]
    assert "sleeves" in seen["description"]


def test_facts_accumulate_rather_than_replace(running):
    store, worker, case = running
    store.add_fact(case.case_id, "sleeves", "long, hemmed", "contributor")
    store.add_fact(case.case_id, "net weight", "1,000 kg", "logistics")

    seen = {}
    with patch.object(type(worker.runner), "classify",
                      lambda self, item, on_event=None: seen.update(d=item.description) or answer()):
        worker.run_case(case.case_id)

    assert "long, hemmed" in seen["d"] and "1,000 kg" in seen["d"]
