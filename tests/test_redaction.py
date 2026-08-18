"""The redactor takes the answer out of the agent's input, so it has to be exact.

Every case here is a shape that got past an earlier version of the pattern and
was caught by the build gate rather than by review. Two of them changed the
measured leak count from zero to fifty-eight.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "internal" / "evalset"))
from build_sets import redact_codes  # noqa: E402

GONE = "[code redacted]"


def left(text):
    """What a leak check sees: the codes still readable once spaces are folded."""
    return re.findall(r"\d{4}(?:\.\d{2,4})*", redact_codes(text).replace(" ", ""))


@pytest.mark.parametrize("text, code", [
    ("classified under subheading 6210.40.55, HTSUS", "6210.40.55"),
    # A ten-digit statistical suffix, written as one group of four. Allowing
    # only pairs made the whole string fail rather than match its prefix, and
    # left 6210.40 readable in thirteen development descriptions.
    ("should be classified under subheading 6210.40.5539, Harmonized", "6210.40.5539"),
    ("under 6210.40.55.39 of the schedule", "6210.40.55.39"),
    ("entered under 6202930910", "6202930910"),
    ("the eight digit line 62029309", "62029309"),
    # The layout extractor runs words together. A trailing \b anchor put this
    # one past the gate: `20` and `r` are both word characters.
    ("falls in subheading 8486.20rather than 8486.40", "8486.20"),
    # A code ending a sentence. Rejecting any following dot took the redaction
    # from thirty-eight descriptions down to eleven.
    ("classifiable in subheading 8486.20.", "8486.20"),
])
def test_a_code_the_agent_could_read_is_removed(text, code):
    out = redact_codes(text)
    assert GONE in out
    assert code not in out.replace(" ", "")


def test_every_code_in_a_sentence_goes_not_just_the_first():
    out = redact_codes("we conclude it falls in 8486.20 rather than 8486.40")
    assert out.count(GONE) == 2
    assert not left("we conclude it falls in 8486.20 rather than 8486.40")


def test_the_surrounding_words_are_left_alone():
    """It removes the answer, not the merchandise facts the case turns on."""
    out = redact_codes("Tank capacity is 600 liters; 86 percent nylon, 14 percent spandex.")
    assert out == "Tank capacity is 600 liters; 86 percent nylon, 14 percent spandex."


def test_a_four_digit_year_is_not_a_tariff_code():
    assert redact_codes("the ruling was issued in 2024") == "the ruling was issued in 2024"


def test_it_does_not_look_at_the_answer():
    """Answer-blind by construction: the same input redacts the same way whatever
    the truth happens to be, which is what keeps this from being score tuning."""
    text = "classifiable in 6210.40.55 rather than 6210.40.70"
    assert redact_codes(text).count(GONE) == 2
