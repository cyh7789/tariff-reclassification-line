from pathlib import Path
from unittest.mock import patch

from fleet.triage.engine import triage
from fleet.triage.types import Bucket, LineItem, Route


# Hand-built edge cases, kept apart from the real-snapshot fixture the gate
# tests use: routing rules are easier to read against codes chosen for them.
FIXTURE = Path(__file__).parent / "fixtures" / "triage"


def run_triage(*items: LineItem):
    with patch("fleet.triage.engine.assert_healthy") as gate:
        results = triage(items, FIXTURE)
    gate.assert_called_once_with(FIXTURE, sources=("hts", "correlation"))
    return results


def item(item_id: str, hs_code: str) -> LineItem:
    return LineItem(item_id, "Fixture product", hs_code, "fixtures")


def test_surviving_code_is_deterministic():
    result = run_triage(item("survived", "0101210010"))[0]

    assert result.bucket is Bucket.SURVIVED
    assert result.route is Route.DETERMINISTIC
    assert result.candidates == ()
    assert result.current_duty is not None
    assert result.current_duty.general == "Free"


def test_dead_one_to_one_code_never_routes_to_agent():
    result = run_triage(item("one-to-one", "0101299999"))[0]

    assert result.bucket is Bucket.DEAD_CODE
    assert result.route is Route.DETERMINISTIC
    assert result.selected_code == "010130"
    assert len(result.candidates) == 1


def test_dead_split_code_routes_to_agent():
    result = run_triage(item("split", "2106909999"))[0]

    assert result.bucket is Bucket.DEAD_CODE
    assert result.route is Route.AGENT
    assert result.selected_code is None
    assert {candidate.hs_code for candidate in result.candidates} == {
        "210690",
        "240491",
    }


def test_dead_single_ex_candidate_routes_to_agent():
    result = run_triage(item("partial", "8543709999"))[0]

    assert result.bucket is Bucket.DEAD_CODE
    assert result.route is Route.AGENT
    assert result.candidates[0].is_ex is True


def test_missing_correlation_routes_to_agent():
    result = run_triage(item("missing", "9999999999"))[0]

    assert result.bucket is Bucket.DEAD_CODE
    assert result.route is Route.AGENT
    assert result.candidates == ()
    assert "first principles" in result.reason


def test_surviving_split_source_is_reclassified_for_scope_review():
    result = run_triage(item("scope", "2106909810"))[0]

    assert result.bucket is Bucket.SCOPE_REVIEW
    assert result.route is Route.AGENT
    assert len(result.candidates) == 2
    assert result.current_duty is not None


def test_surviving_single_ex_source_is_reclassified_for_scope_review():
    result = run_triage(item("scope-ex", "8543709810"))[0]

    assert result.bucket is Bucket.SCOPE_REVIEW
    assert result.route is Route.AGENT


def test_preserves_input_order_and_snapshot_id():
    results = run_triage(
        item("first", "9999999999"),
        item("second", "0101210010"),
    )

    assert [result.item_id for result in results] == ["first", "second"]
    assert {result.snapshot_id for result in results} == {"fixture-2026-08-17"}


def test_code_living_only_as_a_ten_digit_row_is_not_reported_dead():
    """A code whose 8-digit level has no row of its own is still current.

    Treating "no 8-digit row" as "code withdrawn" would send 54% of a real
    catalog into the reclassification queue.
    """
    result = run_triage(item("ten-digit-only", "0101300000"))[0]

    assert result.bucket is Bucket.SURVIVED
    assert result.route is Route.DETERMINISTIC
