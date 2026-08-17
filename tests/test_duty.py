from fleet.triage.duty import resolve


def test_resolves_rate_from_matching_eight_digit_row():
    rows = [
        {
            "htsno": "21069098",
            "indent": 2,
            "general": "6.4%",
            "special": "Free (A)",
            "other": "20%",
            "row_index": 8,
        }
    ]

    rate = resolve("2106909810", rows)

    assert rate is not None
    assert rate.hts8 == "21069098"
    assert rate.general == "6.4%"
    assert rate.resolved_from_row == 8
    assert rate.inherited is False


def test_resolves_blank_rate_from_nearest_ancestor():
    rows = [
        {
            "htsno": "010121",
            "indent": 1,
            "general": "Free",
            "special": "",
            "other": "Free",
            "row_index": 12,
        },
        {
            "htsno": "01012100",
            "indent": 2,
            "general": "",
            "special": "",
            "other": "",
            "row_index": 13,
        },
    ]

    rate = resolve("0101210010", rows)

    assert rate is not None
    assert rate.general == "Free"
    assert rate.special is None
    assert rate.resolved_from_row == 12
    assert rate.inherited is True


def test_returns_none_for_missing_eight_digit_code():
    assert resolve("9999999999", []) is None


def test_resolves_rate_when_eight_digit_level_has_no_row_of_its_own():
    """Most US 8-digit codes have no row: the rate sits on the 10-digit row.

    8113 of 14957 distinct 8-digit codes in 2026HTSRev16 appear only as the
    prefix of a 10-digit line, and 8112 of those lines carry the rate directly.
    """
    rows = [
        {
            "htsno": "0101300000",
            "indent": 1,
            "general": "6.8%",
            "special": "Free (A)",
            "other": "15%",
            "row_index": 5,
        }
    ]

    rate = resolve("0101300000", rows)

    assert rate is not None
    assert rate.hts8 == "01013000"
    assert rate.general == "6.8%"
    assert rate.resolved_from_row == 5
    assert rate.inherited is False
