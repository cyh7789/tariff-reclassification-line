"""The extra duty hangs off the footnote, and without it a rate is not the rate.

783 rows in 2026HTSRev16 point at a chapter 99 subheading: 9903.90 on 680 of them,
the Section 301 China list 9903.88 on six. For goods of the wrong origin that
add-on is larger than the base rate, so a duty comparison that omits it is not
incomplete, it is wrong. The contract has said so since v1.1; the fetcher did not.
"""

from fleet.sync.hts import to_record


ROW_WITH_FOOTNOTE = {
    "htsno": "2501.00.00.00", "indent": "1", "description": "Salt",
    "general": "Free", "special": "", "other": "Free", "units": ["kg"],
    "footnotes": [{"columns": ["desc"], "value": "See 9903.90.08. ", "type": "endnote"}],
    "additionalDuties": None,
    "addiitionalDuties": None,          # the misspelt field upstream ships, always null
}

ROW_WITH_SAFEGUARD = {
    "htsno": "9904.02.01", "indent": "1", "description": "Agricultural safeguard",
    "general": "", "special": "", "other": "", "units": [],
    "footnotes": [], "additionalDuties": "66.6¢/kg",
}


def test_a_footnote_pointing_at_chapter_99_survives_into_the_snapshot():
    record = to_record(ROW_WITH_FOOTNOTE, 0)

    assert record["footnotes"] == [{"columns": ["desc"], "value": "See 9903.90.08.",
                                    "type": "endnote"}]


def test_the_agricultural_safeguard_column_survives():
    assert to_record(ROW_WITH_SAFEGUARD, 0)["additional_duties"] == "66.6¢/kg"


def test_a_row_with_neither_carries_empty_values_rather_than_missing_keys():
    record = to_record({"htsno": "0101.21.00", "indent": "2", "description": "Other",
                        "general": "Free", "units": []}, 0)

    assert record["footnotes"] == []
    assert record["additional_duties"] is None


def test_the_misspelt_upstream_field_is_not_carried():
    """`addiitionalDuties` is null on every row; carrying it invites a wrong read."""
    assert "addiitionalDuties" not in to_record(ROW_WITH_FOOTNOTE, 0)
