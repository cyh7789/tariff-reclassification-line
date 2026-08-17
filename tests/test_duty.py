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
