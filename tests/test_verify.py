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
    """The schedule prints curly quotes; a model writes straight ones or none."""
    assert (normalize_words('the term “poplin” means')
            == normalize_words("the term 'poplin' means")
            == normalize_words("the term poplin means"))


# ---------------------------------------------------------------------------
# Faithful quotes that the first version of the verifier wrongly rejected.
# All three came out of the first development run; none is a paraphrase.
# ---------------------------------------------------------------------------

HTS_ROWS = [
    {"htsno": "6201", "indent": 0, "row_index": 0,
     "description": "Men's or boys' overcoats, carcoats, capes, cloaks, anoraks "
                    "(including ski jackets), windbreakers and similar articles "
                    "(including padded, sleeveless jackets), other than those of heading 6203:"},
    {"htsno": None, "indent": 1, "row_index": 1, "description": "Of man-made fibers:"},
    {"htsno": "62014075", "indent": 2, "row_index": 2, "description": "Other"},
    {"htsno": "6201407510", "indent": 3, "row_index": 3, "description": "Men's (634)"},
]


class FakeHtsSnapshot:
    hts = HTS_ROWS
    notes = {"74": "1.   In this chapter the following expressions have the meanings\n"
                   "     hereby assigned to them:\n\n"
                   "     (b) Copper alloys\n\n"
                   "          Metallic substances other than unrefined copper in which\n"
                   "          copper predominates by weight over each of the other elements,\n"
                   "          provided that:\n",
             "42": '1.   For the purposes of heading 4202, the expression “travel, sports\n'
                   '     and similar bags” means goods of a kind described there.\n'}


@pytest.fixture(scope="module")
def hts_verifier():
    return CitationVerifier(snapshot=FakeHtsSnapshot(), known_rulings=set())


def test_a_tariff_line_quoted_with_its_inherited_text_resolves(hts_verifier):
    """A line's legal description is its ancestors' text plus its own.

    CBP writes them that way: `Mechanical appliances ...: Agricultural or
    horticultural sprayers: Other`. Comparing only against the leaf row, whose
    description is the single word `Other`, rejects the correct form of citation.
    """
    result = hts_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "tariff_line", "ref": "6201.40.75",
                    "quote": "Men's or boys' overcoats, carcoats, capes, cloaks, anoraks "
                             "(including ski jackets), windbreakers and similar articles: "
                             "Of man-made fibers: Other"}],
    ))

    assert result.passed, result.reason


def test_a_heading_joined_to_its_body_by_a_colon_resolves(hts_verifier):
    """`(b) Copper alloys` and its definition sit in separate paragraphs."""
    result = hts_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 1 to Chapter 74",
                    "quote": "Copper alloys: Metallic substances other than unrefined "
                             "copper in which copper predominates by weight over each "
                             "of the other elements"}],
    ))

    assert result.passed, result.reason


def test_a_different_quote_mark_style_resolves(hts_verifier):
    """The schedule uses typographic double quotes; models often write single."""
    result = hts_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 1 to Chapter 42",
                    "quote": "the expression 'travel, sports and similar bags' means goods"}],
    ))

    assert result.passed, result.reason


def test_paraphrase_still_fails_after_all_that_loosening(hts_verifier):
    """The point of the three tests above is not to stop checking."""
    result = hts_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 1 to Chapter 74",
                    "quote": "Copper alloys are mixtures where copper is the main "
                             "component by mass compared with every other element"}],
    ))

    assert not result.passed
    assert "not found in the cited source" in result.reason


def test_a_paraphrase_that_contains_a_colon_still_fails(hts_verifier):
    """Splitting on colons is the one place this check was loosened.

    A paraphrase carrying a colon gets split the same way a legitimate join does,
    so each piece gets its own chance to be found. It still has to fail, because
    the words inside each piece were altered.
    """
    result = hts_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 1 to Chapter 74",
                    "quote": "Copper alloys: mixtures in which copper outweighs every "
                             "other constituent element by mass"}],
    ))

    assert not result.passed
    assert "not found in the cited source" in result.reason


class FakeSectionSnapshot:
    hts = HTS_ROWS
    notes = {"84": "1.   This chapter does not cover millstones of heading 6804.\n"}
    section_notes = {"XVI": "6.   Machines used for more than one purpose are classified\n"
                            "     according to their principal function.\n"}
    chapter_sections = {"84": "XVI"}


@pytest.fixture(scope="module")
def section_verifier():
    return CitationVerifier(snapshot=FakeSectionSnapshot(), known_rulings=set())


def test_a_section_note_resolves(section_verifier):
    """Section XVI governs chapters 84 and 85, so machinery cites it constantly.

    Four of the five citation failures in the first development run were this
    reference being unparseable rather than wrong.
    """
    result = section_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 6 to Section XVI",
                    "quote": "Machines used for more than one purpose are classified "
                             "according to their principal function"}],
    ))

    assert result.passed, result.reason


def test_a_section_note_number_that_does_not_exist_fails(section_verifier):
    result = section_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 99 to Section XVI"}],
    ))

    assert not result.passed
    assert "no note 99" in result.reason


def test_a_section_that_does_not_exist_fails(section_verifier):
    result = section_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 1 to Section XCIX"}],
    ))

    assert not result.passed


def test_a_chapter_note_quoted_against_the_section_does_not_pass(section_verifier):
    """Keeping the two apart is the point; a section note is not a chapter note."""
    result = section_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 1 to Chapter 84",
                    "quote": "Machines used for more than one purpose are classified "
                             "according to their principal function"}],
    ))

    assert not result.passed


# ---------------------------------------------------------------------------
# Three real disagreements from the second full development run. One of them is
# the verifier working; the other two are it being wrong. Telling them apart is
# the whole design question, so all three are pinned here.
# ---------------------------------------------------------------------------

class FakeRealCases:
    hts = HTS_ROWS
    notes = {
        # Chapter 90 note 2(a), verbatim, with no comma before "are in all cases".
        "90": "2.   Subject to note 1 above, parts and accessories are to be classified:\n\n"
              "     (a) parts and accessories which are goods included in any of the headings\n"
              "     of this chapter or of chapter 84, 85 or 91 (other than heading 8487, 8548\n"
              "     or 9033) are in all cases to be classified in their respective headings;\n",
        # Chapter 95 note 1(x), with the footnote marker the PDF layout leaves behind.
        "95": "1.   This chapter does not cover:\n\n"
              "     (x) toilet articles, carpets, apparel, bed linen, table linen, toilet\n"
              "     linen, 1/ kitchen linen and similar articles having a utilitarian\n"
              "     function (classified according to their constituent material).\n",
    }
    section_notes = {
        # Section XV note 5(a): the source says "an alloy of base metals", full stop.
        "XV": "5.   Classification of alloys:\n\n"
              "     (a) an alloy of base metals is to be classified as an alloy of the metal\n"
              "     which predominates by weight over each of the other metals.\n",
    }
    chapter_sections = {"90": "XV", "95": "XV"}


@pytest.fixture(scope="module")
def real_verifier():
    return CitationVerifier(snapshot=FakeRealCases(),
                            known_rulings={"N359078", "965970", "F81541"})


def test_an_added_comma_is_not_a_misquote(real_verifier):
    """N357291 quoted note 2(a) with a comma the schedule does not print."""
    result = real_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 2 (a) to Chapter 90",
                    "quote": "of chapter 84, 85 or 91 (other than heading 8487, 8548 or 9033), "
                             "are in all cases to be classified in their respective headings"}],
    ))

    assert result.passed, result.reason


def test_a_footnote_marker_left_by_the_pdf_is_not_a_misquote(real_verifier):
    """N339765 quoted note 1(x); the source carries a stray `1/` mid-sentence."""
    result = real_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 1 to Chapter 95",
                    "quote": "bed linen, table linen, toilet linen, kitchen linen and similar "
                             "articles having a utilitarian function"}],
    ))

    assert result.passed, result.reason


def test_inserted_words_are_still_a_misquote(real_verifier):
    """N351692 wrote "an alloy of base metals of this section"; the note does not.

    This is the case the whole check exists for, and the two tests above must not
    be allowed to forgive it: punctuation is transcription, words are substance.
    """
    result = real_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "chapter_note", "ref": "Note 5 to Section XV",
                    "quote": "an alloy of base metals of this section is to be classified as "
                             "an alloy of the metal which predominates by weight"}],
    ))

    assert not result.passed
    assert "not found in the cited source" in result.reason


@pytest.mark.parametrize("ref,bare", [
    ("NY N359078", "N359078"),
    ("HQ 965970", "965970"),
    ("NY F81541", "F81541"),
])
def test_a_ruling_cited_the_way_cbp_writes_it_resolves(real_verifier, ref, bare):
    """CBP writes `NY N359078`; the corpus keys on the bare number.

    Eleven of the twelve citation failures in the second run were this.
    """
    result = real_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "ruling", "ref": ref}],
    ))

    assert result.passed, result.reason


def test_a_fabricated_ruling_still_fails_with_a_prefix(real_verifier):
    result = real_verifier.check(answer(
        selected_code_8="62014075",
        citations=[{"kind": "ruling", "ref": "NY N999999"}],
    ))

    assert not result.passed


class TestRejectionAuthorities:
    """The most forgeable lines on the screen are the ones nothing was checking.

    A candidate ruled out "because heading 8549 covers electrical waste" is
    indistinguishable from a static map of heading prefixes to canned sentences,
    unless the authority it names is resolved against the snapshot.
    """

    #: Codes and rulings that exist in the fixture snapshot, so the test is about
    #: the rejections rather than about the answer around them.
    def answer(self, rejected):
        return {"item_id": "T-1", "status": "CLASSIFIED", "selected_code_8": "01012100",
                "citations": [{"kind": "tariff_line", "ref": "01012100"}],
                "rejected": rejected}

    def test_a_candidate_ruled_out_on_a_ruling_that_does_not_exist_fails(self, verifier):
        verdict = verifier.check(self.answer(
            [{"code": "01012900", "why": "not a purebred", "ref": "N999999"}]))

        assert not verdict.passed
        assert "does not exist" in verdict.reason

    def test_an_hq_ruling_is_a_bare_number_and_still_resolves(self, verifier):
        """CBP numbers NY rulings with a letter and HQ rulings without one."""
        assert verifier._infer_kind("HQ 963283") == "ruling"
        assert verifier._infer_kind("N323816") == "ruling"
        assert verifier._infer_kind("Note 6 to Section XVI") == "chapter_note"
        assert verifier._infer_kind("8524.11") == "tariff_line"

    def test_ruling_out_without_naming_anything_is_recorded_but_not_fatal(self, verifier):
        """The prompt asks for the authority; 16% of real lines still omit it, and
        failing those would throw away good classifications over a missing field."""
        verdict = verifier.check(self.answer([{"code": "01012900", "why": "not a purebred"}]))

        assert verdict.passed
        assert verdict.rejections[0].resolved is False
        assert verdict.bad_rejections == []

    def test_a_real_authority_resolves(self, verifier):
        verdict = verifier.check(self.answer(
            [{"code": "01012900", "why": "not a purebred", "ref": "0101.29"}]))

        assert verdict.passed
        assert verdict.rejections[0].resolved
