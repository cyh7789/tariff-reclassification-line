"""A chapter file opens with its section's notes, then the chapter's own.

Chapter 84's PDF starts with the SECTION XVI notes and only reaches chapter 84's
notes some fifteen thousand characters later. Storing the two as one blob leaves
`Note 6 to Section XVI` with nothing to resolve against, and that reference is not
exotic: section XVI governs chapters 84 and 85, which is where machinery and
electrical goods live. Four of the five citation failures in the first
development run were exactly this reference.
"""

import pytest

from fleet.sync.notes import split_notes


PAGE = """\
                    Harmonized Tariff Schedule of the United States Revision 16 (2026)
                                  Annotated for Statistical Reporting Purposes

                                          SECTION XVI

                        MACHINERY AND MECHANICAL APPLIANCES; ELECTRICAL EQUIPMENT
                                                                              XVI-1
Notes

1.    This section does not cover transmission belts of plastics.

6.    Machines used for more than one purpose are classified by principal function.

                                          CHAPTER 84

                        NUCLEAR REACTORS, BOILERS, MACHINERY AND MECHANICAL APPLIANCES
                                                                               84-1
Notes

1.    This chapter does not cover millstones of heading 6804.

8401.10.00.00      Nuclear reactors                                            Free
"""


def test_the_section_notes_are_separated_from_the_chapter_notes():
    section, chapter = split_notes(PAGE, chapter=84)

    assert "This section does not cover" in section
    assert "This section does not cover" not in chapter
    assert "This chapter does not cover" in chapter
    assert "This chapter does not cover" not in section


def test_the_section_number_is_recovered():
    from fleet.sync.notes import find_section

    assert find_section(PAGE) == "XVI"


def test_neither_half_reaches_the_tariff_lines():
    section, chapter = split_notes(PAGE, chapter=84)

    assert "8401.10.00.00" not in section
    assert "8401.10.00.00" not in chapter


def test_a_chapter_that_opens_a_section_still_yields_both():
    """Only the first chapter of a section carries the section notes."""
    section, chapter = split_notes(PAGE, chapter=84)

    assert section and chapter


def test_a_chapter_with_no_section_notes_yields_an_empty_section_half():
    page = """\
                                          CHAPTER 85

                        ELECTRICAL MACHINERY AND EQUIPMENT
Notes

1.    This chapter does not cover electrically warmed blankets.

8501.10.00.00      Motors                                                      Free
"""
    section, chapter = split_notes(page, chapter=85)

    assert section == ""
    assert "This chapter does not cover" in chapter
