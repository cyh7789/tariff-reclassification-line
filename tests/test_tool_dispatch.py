"""A malformed tool call must come back as an answerable error, not an exception.

Six of 141 items in the first full development run died on `KeyError: 'query'`:
the model called `search_precedents` with only a tariff prefix. Raising there
costs the whole item, including the research already paid for, over an argument
the model would have supplied on the next turn if it had been told.
"""

from pathlib import Path

import pytest

from fleet.agents.classifier import Runner

SNAPSHOT = Path(__file__).parent / "fixtures" / "snapshot"


@pytest.fixture(scope="module")
def dispatcher():
    runner = Runner.__new__(Runner)          # no client, no network
    from fleet.agents.tools import PrecedentIndex, Snapshot
    runner.snapshot = Snapshot(SNAPSHOT)
    runner.index = PrecedentIndex(SNAPSHOT)
    return runner


def test_a_missing_required_argument_returns_an_error(dispatcher):
    result = dispatcher.call_tool("search_precedents", {"tariff_prefix": "8424"})

    assert "error" in result
    assert "query" in result["error"]


def test_the_error_names_the_tool_and_stays_short(dispatcher):
    result = dispatcher.call_tool("get_chapter_notes", {})

    assert "error" in result
    assert "chapter" in result["error"]
    assert len(result["error"]) < 200


def test_an_invalid_argument_value_returns_an_error(dispatcher):
    result = dispatcher.call_tool("get_tariff_lines", {"prefix": "84"})

    assert "error" in result
    assert "4" in result["error"]


def test_an_unknown_tool_returns_an_error(dispatcher):
    result = dispatcher.call_tool("consult_the_oracle", {})

    assert "error" in result


def test_a_well_formed_call_still_works(dispatcher):
    result = dispatcher.call_tool("search_precedents", {"query": "cotton yarn"})

    assert "rulings" in result
