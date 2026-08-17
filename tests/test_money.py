"""What a published rate costs on a shipment.

The rule being protected: a number is produced only when the data supports one.
Nearly a tenth of the schedule charges by weight or by head, and the previous
behaviour was to say nothing at all about those lines, which on screen reads as
"no duty difference here" rather than "somebody has to give me the weight".
"""

from fleet.triage.money import duty_owed, parse_rate


def test_a_plain_percentage_costs_out_from_the_invoice_alone():
    duty = duty_owed(parse_rate("7.1%"), value=250_000)

    assert duty.amount == 17_750
    assert "7.1% of $250,000" in duty.basis


def test_free_is_a_rate_of_zero_not_a_missing_rate():
    duty = duty_owed(parse_rate("Free"), value=250_000)

    assert duty.known and duty.amount == 0


def test_a_specific_rate_needs_the_quantity_and_says_so():
    """The old behaviour was silence, which reads as "nothing owed"."""
    duty = duty_owed(parse_rate("1¢/kg"), value=250_000)

    assert not duty.known
    assert duty.missing == "the quantity in kg"


def test_a_specific_rate_with_the_quantity_costs_out():
    duty = duty_owed(parse_rate("1¢/kg"), value=250_000, quantity=12_000, unit="kg")

    assert duty.amount == 120.0


def test_dollars_per_unit_parse_as_dollars_not_cents():
    duty = duty_owed(parse_rate("$1.646/kg"), value=None, quantity=1_000, unit="kg")

    assert duty.amount == 1_646.0


def test_a_compound_rate_charges_both_parts():
    """$1.104/kg + 14.9% on 1,000 kg worth $50,000."""
    duty = duty_owed(parse_rate("$1.104/kg + 14.9%"), value=50_000,
                     quantity=1_000, unit="kg")

    assert duty.amount == round(1_104 + 7_450, 2)
    assert "×" in duty.basis and "%" in duty.basis


def test_a_quantity_in_the_wrong_unit_is_refused_rather_than_converted():
    """Pounds are not kilos, and guessing the factor invents a duty figure."""
    duty = duty_owed(parse_rate("1¢/kg"), value=None, quantity=500, unit="lb")

    assert not duty.known
    assert "kg" in duty.missing and "lb" in duty.missing


def test_a_rate_stated_in_words_is_handed_to_a_person_verbatim():
    rate = parse_rate("The rate applicable to the natural juice in heading 2009")

    assert not rate.computable
    duty = duty_owed(rate, value=250_000)
    assert not duty.known
    assert "heading 2009" in duty.missing


def test_a_percentage_without_a_value_names_the_value_as_what_is_missing():
    duty = duty_owed(parse_rate("7.1%"), value=None)

    assert not duty.known
    assert duty.missing == "the customs value of the shipment"


def test_the_odd_units_in_the_schedule_survive_parsing():
    """68¢/head is a real line. So are per-dozen and per-liter rates."""
    assert parse_rate("68¢/head").unit == "head"
    assert parse_rate("2.5¢/liter").per_unit == 0.025
    assert parse_rate("$0.33/doz").unit == "doz"


def test_a_compound_rate_missing_its_weight_still_reports_the_part_it_can():
    """49.7¢/kg + 19.7% on a $100,000 invoice with no weight: the officer can be
    told $19,700 and exactly what is still outstanding."""
    duty = duty_owed(parse_rate("49.7¢/kg + 19.7%"), value=100_000)

    assert not duty.known and duty.partial
    assert duty.subtotal == 19_700
    assert duty.missing == "the quantity in kg"
    assert "19.7% of $100,000" in duty.subtotal_basis


def test_a_purely_specific_rate_has_no_part_to_report():
    duty = duty_owed(parse_rate("1¢/kg"), value=100_000)

    assert not duty.known and not duty.partial and duty.subtotal is None
