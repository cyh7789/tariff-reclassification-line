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


HTS_ROWS.extend([
    {"htsno": "02013000", "indent": 3, "row_index": 30, "description": "Boneless",
     "general": "26.4%", "special": "", "other": "31.1%", "footnotes": []},
    {"htsno": "04061000", "indent": 3, "row_index": 31, "description": "Fresh cheese",
     "general": "$1.104/kg", "special": "", "other": "20%", "footnotes": []},
    {"htsno": "20096100", "indent": 3, "row_index": 32, "description": "Grape juice",
     "general": "The rate applicable to the natural juice in heading 2009",
     "special": "", "other": "", "footnotes": []},
])


def test_a_rate_charged_by_weight_is_costed_when_the_quantity_is_known():
    out = assess(case(selected_code="04061000", runner_up_code="04061000",
                      quantity=1_000, quantity_unit="kg"), FakeSnapshot(), SCREENING)

    found = next(f for f in out if f.kind == "DUTY_BY_QUANTITY")
    assert "$1,104" in found.detail


def test_a_rate_charged_by_weight_without_a_quantity_is_named_not_ignored():
    """Silence here reads as "no duty", which is the expensive kind of wrong."""
    out = assess(case(selected_code="04061000", runner_up_code="04061000"),
                 FakeSnapshot(), SCREENING)

    found = next(f for f in out if f.kind == "DUTY_NOT_COMPUTABLE")
    assert found.severity is Severity.HUMAN
    assert "the quantity in kg" in found.headline


def test_a_rate_written_in_words_goes_to_a_person_with_the_words():
    out = assess(case(selected_code="20096100", runner_up_code="20096100"),
                 FakeSnapshot(), SCREENING)

    found = next(f for f in out if f.kind == "DUTY_NOT_COMPUTABLE")
    assert "heading 2009" in found.detail


HTS_ROWS.extend([
    {"htsno": "12023080", "indent": 3, "row_index": 40, "description": "Other",
     "general": "9.35¢/kg", "special": "", "other": "", "footnotes":
     [{"value": "See 9903.88.03.", "columns": ["desc"], "type": "endnote"}]},
    {"htsno": "12023040", "indent": 3, "row_index": 41, "description": "Seed",
     "general": "9.35¢/kg", "special": "", "other": "", "footnotes": []},
])


def test_the_eighth_digit_deciding_the_301_exposure_is_flagged_for_review():
    """In 408 six-digit subheadings some eight-digit lines carry a chapter 99
    footnote and their siblings do not, so the choice decides whether the add-on
    is owed. That raises the review priority."""
    out = assess(case(selected_code="12023080", runner_up_code="12023080",
                      quantity=100, quantity_unit="kg"), FakeSnapshot(), SCREENING)

    flag = next(f for f in out if f.kind == "HIGH_STAKES_CLASSIFICATION")
    assert "120230" in flag.detail
    assert flag.severity is Severity.INFO


def test_siblings_that_agree_on_the_exposure_raise_nothing():
    out = assess(case(selected_code="84212100", runner_up_code="84212100"),
                 FakeSnapshot(), SCREENING)

    assert "HIGH_STAKES_CLASSIFICATION" not in kinds(out)


def test_the_duty_consequence_never_reaches_the_classifier():
    """The structural version of the rule that a tax result must not pick the
    legal answer: what the agent is shown is built from the prior code, the
    correlation candidates and the goods, and there is no path for a finding to
    enter it."""
    from fleet.agents.classifier import Item, render_item

    shown = render_item(Item(item_id="T", description="a jacket", prior_hs6="620111",
                             candidates=[{"hs_code": "620120", "is_ex": True,
                                          "relationship": "1:n", "is_sweep": False}]))

    for word in ("9903", "chapter 99", "Section 301", "duty", "rate"):
        assert word.lower() not in shown.lower()


def test_every_listed_party_a_supplier_resembles_is_raised():
    """One name can resemble several listed parties, and the person confirming
    identity needs all of them. Stopping at the first hit means whichever entry
    happens to sit earlier in a 25,939-row file decides what a person gets to
    see, and a weak resemblance can hide a strong one behind it."""
    lists = [
        {"name": "Orient", "source_list": "Entity List"},
        {"name": "Orient Precision Industries", "source_list": "SDN List",
         "license_requirement": "Presumption of denial"},
    ]
    out = assess(case(supplier="Orient Precision Industries Co., Ltd."),
                 FakeSnapshot(), lists)

    hits = [f for f in out if f.kind == "SCREENING_MATCH"]
    assert len(hits) == 2, "both listed parties resemble this supplier"
    assert "SDN List" in " ".join(f.detail for f in hits)


def test_a_short_listed_name_does_not_match_inside_a_longer_word():
    """Measured on the real list once the demo catalog carried suppliers:
    "Nordvale Diagnostics BV" was reported as resembling "TIC LTD", because
    stripping the corporate suffix leaves "tic", which is a substring of
    "diagnostics". Five of twenty items matched that way. A person handed that
    noise stops reading the flag."""
    lists = [{"name": "TIC LTD", "source_list": "Denied Persons List"},
             {"name": "ALE", "source_list": "SDN List"},
             {"name": "LIA", "source_list": "SDN List"}]
    for supplier in ("Nordvale Diagnostics BV", "Aurelia Coated Fabrics"):
        out = assess(case(supplier=supplier), FakeSnapshot(), lists)
        assert "SCREENING_MATCH" not in kinds(out), f"{supplier} is not any of these"


def test_a_real_resemblance_still_matches():
    """The one it must never miss: the same name with corporate furniture on it."""
    lists = [{"name": "NEL Electronics", "source_list": "Entity List",
              "license_requirement": "For all items subject to the EAR."}]
    out = assess(case(supplier="NEL Electronics Pte Ltd"), FakeSnapshot(), lists)

    assert "SCREENING_MATCH" in kinds(out)


def test_an_iso_country_code_counts_as_the_country():
    """An ERP export writes CN, not "China". The chapter 99 add-on read a set of
    prose names, so every catalog that used codes silently owed nothing."""
    from fleet.findings.engine import SECTION_301_ORIGINS, _origin_key

    assert _origin_key("CN") in SECTION_301_ORIGINS
    assert _origin_key("China") in SECTION_301_ORIGINS
    assert _origin_key("HK") in SECTION_301_ORIGINS
    assert _origin_key("VN") not in SECTION_301_ORIGINS
