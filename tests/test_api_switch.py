"""Nothing calls a paid endpoint unless somebody switched it on for that command.

This exists because six development runs cost $36 of a credit belonging to a
different project, and none of them was started by a decision to spend money.
They were started because the code made it easy. A promise not to do that again
is worth nothing; a gate that raises is worth the test.
"""

import pytest

from fleet.agents.classifier import ApiDisabled, assert_api_allowed, default_flex


def test_the_default_is_off(monkeypatch):
    monkeypatch.delenv("FLEET_ALLOW_API", raising=False)

    with pytest.raises(ApiDisabled) as exc:
        assert_api_allowed()
    assert "switched off" in str(exc.value)


def test_anything_other_than_the_exact_switch_is_still_off(monkeypatch):
    """"true", "yes" and "1 " are the shapes a hurried export takes."""
    for value in ("true", "yes", "0", "", " 1"):
        monkeypatch.setenv("FLEET_ALLOW_API", value)
        with pytest.raises(ApiDisabled):
            assert_api_allowed()


def test_switching_it_on_is_explicit(monkeypatch):
    monkeypatch.setenv("FLEET_ALLOW_API", "1")

    assert_api_allowed()


def test_the_cheap_tier_is_what_you_get_without_asking(monkeypatch):
    """Flex is half price. It was chosen once and quietly reverted once."""
    monkeypatch.delenv("FLEET_TIER", raising=False)
    assert default_flex() is True

    monkeypatch.setenv("FLEET_TIER", "standard")
    assert default_flex() is False
