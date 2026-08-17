"""The record of how one case was worked.

What is being protected here is legibility of the middle. An answer plus a
spinner is what a scripted pipeline looks like from outside; the eliminations,
each naming the note that killed a candidate, are what only a real run produces.
So the tests assert that the losing side survives into the transcript, in order,
attributed to whoever actually did the work.
"""

from dataclasses import dataclass

from fleet.agents.classifier import summarize
from fleet.workflow.transcript import steps


@dataclass
class Verdict:
    passed: bool
    reason: str = ""


ANSWER = {
    "status": "CLASSIFIED",
    "selected_code": "8424419000",
    "selected_code_8": "84244190",
    "runner_up_code": "84248900",
    "distinguishing_fact": "mounted on a tractor, so it is agricultural",
    "confidence": 0.93,
    "tool_calls": [
        {"name": "get_chapter_notes", "args": {"chapter": "84"},
         "result": "8123 characters of notes"},
        {"name": "search_precedents", "args": {"tariff_prefix": "8424"},
         "result": "12 rulings, newest 2024-03-02"},
    ],
    "rejected": [
        {"code": "85285900", "why": "sweep heading for display modules",
         "ref": "Note 7 to Chapter 85"},
        {"code": "85495900", "why": "covers electronic waste, not working machines",
         "ref": "Note 4 to Chapter 85"},
    ],
    "citations": [{"kind": "tariff_line", "ref": "8424419000", "quote": "Sprayers"}],
}


def kinds(rows):
    return [r["kind"] for r in rows]


def test_every_rejected_candidate_gets_its_own_line_with_the_reason():
    """Thirteen sweep headings ruled out is thirteen lines, not a count."""
    rows = steps(ANSWER, Verdict(True))

    rejects = [r for r in rows if r["kind"] == "reject"]
    assert [r["text"] for r in rejects] == ["85285900 ruled out", "85495900 ruled out"]
    assert rejects[0]["detail"] == "sweep heading for display modules"
    assert rejects[0]["ref"] == "Note 7 to Chapter 85"


def test_the_order_is_research_then_eliminations_then_the_decision():
    assert kinds(steps(ANSWER, Verdict(True))) == [
        "tool", "tool", "reject", "reject", "select", "cite", "verify"]


def test_a_tool_line_carries_its_arguments_and_what_came_back():
    rows = steps(ANSWER, None)

    assert rows[0]["text"] == "get_chapter_notes(chapter=84)"
    assert rows[1]["text"] == "search_precedents(tariff_prefix=8424)"
    assert rows[1]["detail"] == "12 rulings, newest 2024-03-02"


def test_the_selected_code_is_never_also_listed_as_rejected():
    """A model that rejects its own answer is contradicting the outcome below."""
    answer = ANSWER | {"rejected": [{"code": "84244190", "why": "confused"}]}

    assert "reject" not in kinds(steps(answer, None))


def test_the_citation_check_is_attributed_to_the_checker_not_the_agent():
    rows = steps(ANSWER, Verdict(False, "quote not found in Note 7 to Chapter 85"))

    check = rows[-1]
    assert check["actor"] == "checker"
    assert check["text"] == "citation check failed"
    assert "Note 7" in check["detail"]


def test_a_refusal_ends_with_the_question_and_who_holds_the_answer():
    answer = {"status": "NEEDS_INPUT", "tool_calls": [],
              "missing_property": "what is the housing material?",
              "ask_department": "engineering"}
    rows = steps(answer, None)

    assert rows[-1]["kind"] == "refuse"
    assert "housing material" in rows[-1]["text"]
    assert "engineering" in rows[-1]["detail"]
    assert "select" not in kinds(rows)


def test_a_search_that_found_nothing_reads_differently_from_one_that_did():
    """The call is identical either way; only the result tells them apart."""
    assert summarize("search_precedents", {"rulings": []}) == "no rulings"
    assert summarize("search_precedents", {"rulings": [{"ruling_date": "2024-01-05"}]}) \
        == "1 rulings, newest 2024-01-05"


def test_a_failed_tool_call_says_so_in_the_transcript():
    assert summarize("get_tariff_lines", {"error": "needs a prefix of 4 to 8 digits"}) \
        == "needs a prefix of 4 to 8 digits"


def test_tariff_lines_are_counted_by_how_many_carry_a_rate():
    """Rates hang on the eighth digit, so "9 lines" and "9 lines, 2 priced" are
    different research and the transcript should not flatten them."""
    result = {"lines": [{"general": "2.4%"}, {"general": ""}, {"general": "Free"}]}

    assert summarize("get_tariff_lines", result) == "3 lines, 2 with a duty rate"
