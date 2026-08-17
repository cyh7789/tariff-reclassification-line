"""What the classification turns out to mean for the importer.

Choosing the code is the hard part; what it costs follows from it. These findings
exist so the officer sees the consequence rather than a number she has to look up
herself, and so the ones a machine should not decide are marked as such rather
than quietly decided anyway.

The line that matters: a finding is either computed from the schedule, in which
case it is stated, or it rests on a judgement about identity, in which case it is
raised for a person. Nothing in between.
"""

import pytest

from fleet.findings.engine import Finding, Severity, assess

HTS_ROWS = [
    {"htsno": "62014070", "indent": 3, "row_index": 10, "description": "Other",
     "general": "7.1%", "special": "Free (AU)", "other": "90%", "footnotes": []},
    {"htsno": "62014075", "indent": 3, "row_index": 11, "description": "Other",
     "general": "27.7%", "special": "", "other": "90%",
     "footnotes": [{"value": "See 9903.88.15.", "columns": ["desc"], "type": "endnote"}]},
    {"htsno": "84212100", "indent": 3, "row_index": 20, "description": "Filtering",
     "general": "Free", "special": "", "other": "35%", "footnotes": []},
]


class FakeSnapshot:
    hts = HTS_ROWS


SCREENING = [
    {"name": "Acme Precision Works", "source_list": "Entity List",
     "license_requirement": "Presumption of denial"},
]


def case(**kw):
    base = dict(item_id="SKU-1", prior_code="620140", selected_code="6201407500",
                runner_up_code="6201407000", country_of_origin=None,
                annual_value=None, supplier=None)
    base.update(kw)
    return base


def kinds(findings):
    return {f.kind for f in findings}


def test_the_stake_of_the_decision_is_always_stated():
    """Every judged item carries what the choice was worth, right or wrong."""
    out = assess(case(), FakeSnapshot(), SCREENING)

    stake = next(f for f in out if f.kind == "DECISION_STAKE")
    assert "20.6" in stake.detail
    assert stake.severity is Severity.INFO


def test_two_codes_at_the_same_rate_raise_no_stake():
    out = assess(case(selected_code="62014070", runner_up_code="62014070"),
                 FakeSnapshot(), SCREENING)

    assert "DECISION_STAKE" not in kinds(out)


def test_a_higher_new_rate_is_an_underpayment_with_a_number():
    """The prior code was cheaper, so every entry since has underpaid."""
    out = assess(case(prior_code="62014070", selected_code="62014075",
                      annual_value=250_000), FakeSnapshot(), SCREENING)

    under = next(f for f in out if f.kind == "UNDERPAID_DUTY")
    assert under.severity is Severity.ACTION
    assert "51,500" in under.detail        # 250,000 × (27.7% − 7.1%)


def test_a_lower_new_rate_is_money_back_not_an_alarm():
    out = assess(case(prior_code="62014075", selected_code="62014070",
                      annual_value=250_000), FakeSnapshot(), SCREENING)

    over = next(f for f in out if f.kind == "OVERPAID_DUTY")
    assert over.severity is Severity.INFO
    assert "51,500" in over.detail


def test_no_import_value_means_the_rate_gap_is_stated_without_a_figure():
    """The value is the importer's own number. Inventing one would be a lie."""
    out = assess(case(prior_code="62014070", selected_code="62014075"),
                 FakeSnapshot(), SCREENING)

    under = next(f for f in out if f.kind == "UNDERPAID_DUTY")
    assert "20.6" in under.detail
    assert "$" not in under.detail


def test_a_six_digit_prior_code_cannot_support_a_comparison():
    """Rates hang on eight digits; six is not a rate, so nothing is claimed."""
    out = assess(case(prior_code="620140", selected_code="62014075"),
                 FakeSnapshot(), SCREENING)

    assert "UNDERPAID_DUTY" not in kinds(out)
    assert "OVERPAID_DUTY" not in kinds(out)


def test_chinese_origin_on_a_301_line_is_flagged():
    out = assess(case(selected_code="62014075", country_of_origin="China"),
                 FakeSnapshot(), SCREENING)

    extra = next(f for f in out if f.kind == "ADDITIONAL_DUTY")
    assert "9903.88.15" in extra.detail
    assert extra.severity is Severity.ACTION


def test_the_same_line_from_elsewhere_is_not_flagged():
    out = assess(case(selected_code="62014075", country_of_origin="Vietnam"),
                 FakeSnapshot(), SCREENING)

    assert "ADDITIONAL_DUTY" not in kinds(out)


def test_a_line_without_a_chapter_99_footnote_is_not_flagged():
    out = assess(case(selected_code="84212100", runner_up_code="84212100",
                      country_of_origin="China"), FakeSnapshot(), SCREENING)

    assert "ADDITIONAL_DUTY" not in kinds(out)


def test_a_supplier_on_the_screening_list_goes_to_a_person():
    """Name matching is similarity, and similarity is not identity."""
    out = assess(case(supplier="Acme Precision Works Ltd"), FakeSnapshot(), SCREENING)

    hit = next(f for f in out if f.kind == "SCREENING_MATCH")
    assert hit.severity is Severity.HUMAN
    assert "Entity List" in hit.detail
    assert "confirm" in hit.detail.lower()


def test_an_unrelated_supplier_produces_nothing():
    out = assess(case(supplier="Northwind Fasteners"), FakeSnapshot(), SCREENING)

    assert "SCREENING_MATCH" not in kinds(out)


def test_findings_come_back_worst_first():
    out = assess(case(prior_code="62014070", selected_code="62014075",
                      country_of_origin="China", supplier="Acme Precision Works",
                      annual_value=100_000), FakeSnapshot(), SCREENING)

    assert [f.severity for f in out] == sorted([f.severity for f in out],
                                               key=lambda s: list(Severity).index(s))
    assert out[0].severity in (Severity.HUMAN, Severity.ACTION)
