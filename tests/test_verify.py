"""The verifier's job is to catch a citation that was never read.

Every case here is built from the fixture snapshot, so the tests run offline. The
one that matters most is `test_a_paraphrased_note_does_not_pass`: a fabricated
reference usually looks right and reads plausibly, and the only thing separating
it from a real one is whether the words are actually there.
"""

import json
from pathlib import Path

import pytest

from fleet.verify.citations import CitationVerifier, normalize_words

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot"


@pytest.fixture(scope="module")
def verifier():
    return CitationVerifier(FIXTURE)


@pytest.fixture(scope="module")
def real_note(verifier):
    """A note number and a verbatim phrase that genuinely appear in chapter 85."""
    notes = verifier.snapshot.notes["85"]
    assert notes.lstrip().startswith("1."), "fixture chapter 85 should open on note 1"
    phrase = "This chapter does not cover"
    assert phrase in notes
    return phrase


def answer(**overrides):
    base = {
        "item_id": "T-1",
        "status": "CLASSIFIED",
        "selected_code_8": None,
        "citations": [],
    }
    base.update(overrides)
    return base


def first_code(verifier, length=8):
    return next(c for c in sorted(verifier._codes) if len(c) >= length)[:length]


def test_a_real_tariff_line_resolves(verifier):
    code = first_code(verifier)
    result = verifier.check(answer(
        selected_code_8=code,
        citations=[{"kind": "tariff_line", "ref": code}],
    ))

    assert result.passed, result.reason


def test_an_invented_tariff_line_fails(verifier):
    code = first_code(verifier)
    result = verifier.check(answer(
        selected_code_8=code,
        citations=[{"kind": "tariff_line", "ref": "99999999"}],
    ))

    assert not result.passed
    assert "do not resolve" in result.reason


def test_an_invented_ruling_fails(verifier):
    code = first_code(verifier)
    result = verifier.check(answer(
        selected_code_8=code,
        citations=[{"kind": "ruling", "ref": "N999999"}],
    ))

    assert not result.passed
    assert "N999999" in result.reason


def test_a_real_chapter_note_resolves(verifier, real_note):
    code = first_code(verifier)
    result = verifier.check(answer(
        selected_code_8=code,
        citations=[{"kind": "chapter_note", "ref": "Note 1 to Chapter 85",
                    "quote": real_note}],
    ))

    assert result.passed, result.reason


def test_a_paraphrased_note_does_not_pass(verifier):
    """The failure mode this whole module exists for.

    The reference is real, the chapter is real, the note number is real. Only the
    words are invented, which is exactly what a model does when it is filling in a
    citation it did not read.
    """
    code = first_code(verifier)
    result = verifier.check(answer(
        selected_code_8=code,
        citations=[{"kind": "chapter_note", "ref": "Note 1 to Chapter 85",
                    "quote": "This chapter excludes all machinery of any kind whatsoever"}],
    ))

    assert not result.passed
    assert "not found in the cited source" in result.reason


def test_a_note_number_the_chapter_does_not_have_fails(verifier):
    code = first_code(verifier)
    result = verifier.check(answer(
        selected_code_8=code,
        citations=[{"kind": "chapter_note", "ref": "Note 99 to Chapter 85"}],
    ))

    assert not result.passed
    assert "no note 99" in result.reason


def test_classifying_with_no_citations_fails(verifier):
    result = verifier.check(answer(selected_code_8=first_code(verifier)))

    assert not result.passed
    assert result.reason == "classified with no citations"


def test_a_selected_code_outside_the_schedule_fails(verifier):
    result = verifier.check(answer(
        selected_code_8="00000000",
        citations=[{"kind": "tariff_line", "ref": first_code(verifier)}],
    ))

    assert not result.passed
    assert "not in the schedule" in result.reason


def test_refusing_passes_when_it_names_what_is_missing(verifier):
    result = verifier.check(answer(
        status="NEEDS_INPUT",
        selected_code_8=None,
        missing_property="what is the housing material?",
    ))

    assert result.passed


def test_refusing_while_still_shipping_a_code_fails(verifier):
    result = verifier.check(answer(
        status="NEEDS_INPUT",
        selected_code_8=first_code(verifier),
        missing_property="what is the housing material?",
    ))

    assert not result.passed
    assert "still produced" in result.reason


def test_refusing_without_saying_what_is_missing_fails(verifier):
    result = verifier.check(answer(status="NEEDS_INPUT", selected_code_8=None))

    assert not result.passed
    assert "without naming what is missing" in result.reason


def test_line_wrapping_does_not_break_a_faithful_quote():
    """PDF extraction wraps mid-sentence; that must not read as paraphrase."""
    wrapped = "This chapter\n     does not   cover\nelectrically warmed blankets"

    assert normalize_words(wrapped) == "this chapter does not cover electrically warmed blankets"


def test_typographic_quotes_do_not_break_a_faithful_quote():
    assert normalize_words('the term “poplin” means') == 'the term "poplin" means'
