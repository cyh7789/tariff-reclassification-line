"""The tariff schedule is a tree whose interior nodes often carry no code.

Rows copied from 2026HTSRev16 around heading 8424. `Agricultural or horticultural
sprayers:` has no code of its own, so a lookup that returns only coded rows hands
the agent two sibling lines with no statement of what they sit under. That is how
a 600-litre tractor-mounted sprayer gets argued about as though the only question
were its capacity.
"""

import pytest

from fleet.agents.tools import get_tariff_lines


ROWS = [
    {"htsno": "8424", "indent": 0, "description": "Mechanical appliances for spraying liquids:",
     "general": "", "row_index": 0},
    {"htsno": "842430", "indent": 1, "description": "Steam or sand blasting machines:",
     "general": "", "row_index": 1},
    {"htsno": "8424301000", "indent": 2, "description": "Sand blasting machines",
     "general": "Free", "row_index": 2},
    {"htsno": None, "indent": 1, "description": "Agricultural or horticultural sprayers:",
     "general": "", "row_index": 3},
    {"htsno": "842441", "indent": 2, "description": "Portable sprayers:",
     "general": "", "row_index": 4},
    {"htsno": "8424411000", "indent": 3,
     "description": "Sprayers (except sprayers, self-contained, having a capacity not over 20 liters)",
     "general": "Free", "row_index": 5},
    {"htsno": "8424419000", "indent": 3, "description": "Other",
     "general": "2.4%", "row_index": 6},
    {"htsno": "8424490000", "indent": 2, "description": "Other",
     "general": "2.4%", "row_index": 7},
]


class FakeSnapshot:
    hts = ROWS


def codes(lines):
    return [line.code for line in lines]


def test_uncoded_ancestor_is_returned_as_context():
    lines = get_tariff_lines(FakeSnapshot(), "842441")

    descriptions = [line.description for line in lines]
    assert "Agricultural or horticultural sprayers:" in descriptions


def test_ancestors_come_before_the_subtree_and_are_marked_as_headings():
    lines = get_tariff_lines(FakeSnapshot(), "842441")

    heading = next(line for line in lines if line.description.startswith("Agricultural"))
    assert heading.is_heading is True
    assert heading.code == ""
    assert lines.index(heading) < min(
        i for i, line in enumerate(lines) if line.code.startswith("842441")
    )


def test_coded_ancestors_are_included_too():
    lines = get_tariff_lines(FakeSnapshot(), "8424411000")

    assert "8424" in codes(lines)
    assert "842441" in codes(lines)


def test_the_subtree_itself_is_complete():
    lines = get_tariff_lines(FakeSnapshot(), "842441")

    assert "8424411000" in codes(lines)
    assert "8424419000" in codes(lines)
    assert "8424490000" not in codes(lines)


def test_a_prefix_shorter_than_four_digits_is_refused():
    with pytest.raises(ValueError):
        get_tariff_lines(FakeSnapshot(), "842")
