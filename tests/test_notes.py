"""The notes heading is not spelled one way.

Every variant below is copied from a real chapter file of 2026HTSRev16. Missing
one does not fail loudly: the chapter lands in the snapshot with an empty notes
string, and the agent is told the chapter has no legal notes when in fact it has
the exclusion that decides the case.
"""

import pytest

from fleet.sync.notes import extract_notes


HEADINGS = [
    pytest.param("Notes", id="chapter-84-bare"),
    pytest.param("Notes:", id="chapter-05-colon"),
    pytest.param("U.S. Notes", id="chapter-99-us"),
    pytest.param("Additional U.S. Notes", id="additional-us"),
    pytest.param("Note", id="singular"),
    pytest.param("Note:", id="singular-colon"),
    pytest.param("Statistical Note", id="chapter-53-statistical"),
]


def page(heading: str) -> str:
    return f"""\
                    Harmonized Tariff Schedule of the United States Revision 16 (2026)
                                  Annotated for Statistical Reporting Purposes

                                          CHAPTER 5

{heading}

1.   This chapter does not cover edible products.

2.   For the purposes of heading 0501, sorting hair by length is not working.

0501.00.00.00       Human hair, unworked                                    Free
0502.10.00.00       Pigs', hogs' or boars' bristles                         Free
"""


@pytest.mark.parametrize("heading", HEADINGS)
def test_every_real_heading_variant_yields_the_notes(heading):
    notes = extract_notes(page(heading))

    assert "This chapter does not cover edible products." in notes
    assert "sorting hair by length" in notes


@pytest.mark.parametrize("heading", HEADINGS)
def test_extraction_stops_before_the_tariff_lines(heading):
    notes = extract_notes(page(heading))

    assert "0501.00.00.00" not in notes
    assert "Human hair" not in notes


@pytest.mark.parametrize("heading", HEADINGS)
def test_page_furniture_is_dropped(heading):
    notes = extract_notes(page(heading))

    assert "Harmonized Tariff Schedule" not in notes
    assert "Annotated for Statistical Reporting" not in notes


def test_a_chapter_without_notes_yields_an_empty_string():
    text = "CHAPTER 53\n\n5301.10.00.00   Flax, raw or retted     Free\n"

    assert extract_notes(text) == ""
