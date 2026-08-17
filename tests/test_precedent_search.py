"""Searching a heading must show what has been classified there.

Ground truth for this file is heading 0309: the whole corpus holds five rulings
under it, all from one Norwegian applicant on one day, all landing on 0309.10.90
(whitefish, cod, shrimp, lobster and shrimp-shell powders). CBP's practice there
is only discoverable from those five.

In the second development run the agent asked exactly the right questions,
`tariff_prefix=0309` with `lobster`, then `crustaceans`, then `krill`, and got
nothing back, because the index required a keyword hit on the one-line subject and
no remaining ruling's title carries any of those words. It then reasoned from the
schedule text and produced a defensible answer that CBP does not use.
"""

import json
from pathlib import Path

import pytest

from fleet.agents.tools import PrecedentIndex

SNAPSHOT = Path(__file__).parent / "fixtures" / "snapshot"

CORPUS = [
    {"ruling_number": "N337243", "ruling_date": "2023-11-01", "tariffs": ["0309.10.9000"],
     "subject": "The tariff classification of Whitefish Powder from Norway",
     "related_rulings": [], "url": ""},
    {"ruling_number": "N337247", "ruling_date": "2023-11-01", "tariffs": ["0309.10.9000"],
     "subject": "The tariff classification of Shrimp Shell Powder from Norway",
     "related_rulings": [], "url": ""},
    {"ruling_number": "N999001", "ruling_date": "2023-01-01", "tariffs": ["8543.70.9860"],
     "subject": "The tariff classification of an ultrasonic cleaner from China",
     "related_rulings": [], "url": ""},
]


@pytest.fixture
def index(tmp_path):
    path = tmp_path / "cross.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in CORPUS))
    return PrecedentIndex(tmp_path)


def numbers(hits):
    return [h.ruling_number for h in hits]


def test_a_prefix_with_no_keyword_still_lists_the_heading(index):
    """"What has been classified under 0309" is a question, not a malformed call."""
    hits = index.search("", tariff_prefix="0309")

    assert set(numbers(hits)) == {"N337243", "N337247"}


def test_a_keyword_that_matches_nothing_does_not_empty_a_prefix_search(index):
    """The failure that cost two items: no title says "lobster", so nothing came back."""
    hits = index.search("lobster", tariff_prefix="0309")

    assert set(numbers(hits)) == {"N337243", "N337247"}


def test_the_keyword_still_ranks_within_the_prefix(index):
    hits = index.search("shrimp shell", tariff_prefix="0309")

    assert numbers(hits)[0] == "N337247"


def test_a_prefix_search_does_not_leak_other_headings(index):
    hits = index.search("cleaner", tariff_prefix="0309")

    assert "N999001" not in numbers(hits)


def test_a_keyword_search_without_a_prefix_is_unchanged(index):
    hits = index.search("ultrasonic cleaner")

    assert numbers(hits) == ["N999001"]


def test_an_empty_search_with_no_prefix_returns_nothing(index):
    assert index.search("") == []
