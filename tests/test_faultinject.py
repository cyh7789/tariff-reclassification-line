"""The injected fault has to be caught by the production checker, not by a stub.

A demo of a control working is worth nothing if the control was told to fail. So
these run the real `CitationVerifier` over the fixture snapshot, and the same
answer has to pass before the injection and fail after it.
"""

from pathlib import Path

import pytest

from fleet.verify.citations import CitationVerifier
from fleet.verify.faultinject import (CHECKED_KINDS, INSERTED_WORD, NothingToInject,
                                      inject)

FIXTURE = Path(__file__).parent / "fixtures" / "snapshot"


@pytest.fixture(scope="module")
def verifier():
    return CitationVerifier(FIXTURE)


@pytest.fixture(scope="module")
def clean(verifier):
    """An answer whose note citation genuinely resolves against the fixture."""
    notes = verifier.snapshot.notes["85"]
    phrase = "This chapter does not cover"
    assert phrase in notes
    code = next(c for c in verifier._codes if len(c) == 8)
    return {"item_id": "T-1", "status": "CLASSIFIED", "selected_code_8": code,
            "citations": [{"kind": "chapter_note", "ref": "Note 1 to Chapter 85",
                           "quote": phrase}]}


def test_the_answer_passes_before_anything_is_injected(verifier, clean):
    assert verifier.check(clean).passed, "the fixture answer must start clean"


def test_the_production_checker_catches_the_injected_quote(verifier, clean):
    faulted, note = inject(clean)
    verdict = verifier.check(faulted)
    assert not verdict.passed
    assert "Note 1 to Chapter 85" in verdict.reason
    assert note["ref"] == "Note 1 to Chapter 85"
    assert INSERTED_WORD in note["altered"] and INSERTED_WORD not in note["original"]


def test_the_original_answer_is_left_alone(verifier, clean):
    before = clean["citations"][0]["quote"]
    inject(clean)
    assert clean["citations"][0]["quote"] == before


def test_the_same_answer_always_yields_the_same_fault(clean):
    assert inject(clean)[1] == inject(clean)[1]


def test_a_ruling_quote_is_not_eligible(verifier):
    """Injecting there would produce a fault that passes, which demonstrates the
    opposite of the point: the corpus holds subjects, not full ruling text."""
    assert "ruling" not in CHECKED_KINDS
    with pytest.raises(NothingToInject):
        inject({"citations": [{"kind": "ruling", "ref": "N351696",
                               "quote": "an alloy in which copper predominates by weight"}]})


def test_a_quote_too_short_to_alter_is_refused():
    with pytest.raises(NothingToInject):
        inject({"citations": [{"kind": "chapter_note", "ref": "Note 1 to Chapter 85",
                               "quote": "does not cover"}]})
