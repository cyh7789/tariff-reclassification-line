"""Reading a precedent is what decides whether it is comparable.

Until now the agent saw only a ruling's one-line subject. In the third
development run it retrieved `N337247 Shrimp Shell Powder -> 0309.10.90`, a
crustacean filed where it had just argued crustaceans do not go, and had no way
to check whether that article was like its own. It fell back on the schedule text
and got the answer CBP does not use.

The leakage rule that governs search governs this too: an evaluation item's own
ruling must not be readable, or the agent can fetch its answer key directly.
"""

import json
from pathlib import Path

import pytest

CORPUS = [
    {"ruling_number": "N337247", "ruling_date": "2023-11-01", "tariffs": ["0309.10.9000"],
     "subject": "The tariff classification of Shrimp Shell Powder from Norway",
     "related_rulings": [], "url": ""},
    {"ruling_number": "N999001", "ruling_date": "2023-01-01", "tariffs": ["8543.70.9860"],
     "subject": "An ultrasonic cleaner", "related_rulings": ["N999002"], "url": ""},
    {"ruling_number": "N999002", "ruling_date": "2022-01-01", "tariffs": ["8543.70.9860"],
     "subject": "A related ultrasonic cleaner", "related_rulings": [], "url": ""},
]

TEXTS = [
    {"rulingNumber": "N337247", "subject": "Shrimp Shell Powder", "url": "",
     "text": "Dear Mr. X:\n\nThe subject merchandise is Shrimp Shell Powder, milled from "
             "the shells of cold-water shrimp.\n\nThe applicable subheading will be "
             "0309.10.9000, which provides for flours and meals.\n"},
    {"rulingNumber": "N999001", "subject": "cleaner", "url": "",
     "text": "Dear Ms. Y:\n\nAn ultrasonic bath with a stainless tank.\n\n"
             "The applicable subheading will be 8543.70.9860.\n"},
    {"rulingNumber": "N999002", "subject": "related cleaner", "url": "",
     "text": "Dear Ms. Y:\n\nA second ultrasonic bath.\n\n"
             "The applicable subheading will be 8543.70.9860.\n"},
]


@pytest.fixture
def snapshot_dir(tmp_path):
    (tmp_path / "cross.jsonl").write_text("".join(json.dumps(r) + "\n" for r in CORPUS))
    (tmp_path / "ruling_text.jsonl").write_text("".join(json.dumps(r) + "\n" for r in TEXTS))
    return tmp_path


@pytest.fixture
def index(snapshot_dir):
    from fleet.agents.tools import PrecedentIndex
    return PrecedentIndex(snapshot_dir, excluded={"N999001"})


@pytest.fixture
def snapshot(snapshot_dir):
    from fleet.agents.tools import Snapshot
    return Snapshot(snapshot_dir)


def test_a_ruling_comes_back_as_the_merchandise_description(snapshot, index):
    from fleet.agents.tools import get_ruling

    result = get_ruling(snapshot, index, "N337247")

    assert "milled from the shells of cold-water shrimp" in result
    assert "0309.10.9000" not in result or "flours and meals" not in result


def test_the_collection_prefix_is_accepted(snapshot, index):
    from fleet.agents.tools import get_ruling

    assert "shrimp" in get_ruling(snapshot, index, "NY N337247").lower()


def test_an_excluded_ruling_is_refused(snapshot, index):
    """The evaluation set is drawn from this corpus; its answers must stay shut."""
    from fleet.agents.tools import get_ruling

    result = get_ruling(snapshot, index, "N999001")

    assert "ultrasonic bath" not in result
    assert "not available" in result.lower()


def test_a_related_ruling_of_an_excluded_one_is_refused(snapshot, index):
    from fleet.agents.tools import get_ruling

    result = get_ruling(snapshot, index, "N999002")

    assert "second ultrasonic bath" not in result
    assert "not available" in result.lower()


def test_a_ruling_with_no_cached_text_says_which_rulings_are_carried(snapshot, index):
    """Silence would read as "nothing here"; the agent needs to know why."""
    from fleet.agents.tools import get_ruling

    result = get_ruling(snapshot, index, "N111111")

    assert "N111111" in result
    assert "2022" in result
