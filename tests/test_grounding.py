"""What the flag is allowed to call an importer's own words."""

from fleet.verify.grounding import FactSource, fact_source

SPRAYER = ("Tractor-mounted horticultural sprayer with a 600-liter tank capacity, "
           "PTO-driven diaphragm pump, and a 12-nozzle boom.")


def source(quote, description=SPRAYER):
    return fact_source(quote, description)


def test_words_lifted_from_the_description_are_the_importers():
    assert source("600-liter tank capacity") is FactSource.DESCRIPTION


def test_nothing_quoted_is_read_off_the_schedule():
    assert source(None) is FactSource.SCHEDULE_INFERENCE
    assert source("") is FactSource.SCHEDULE_INFERENCE


def test_a_quote_the_description_never_contained_does_not_pass():
    assert source("tank capacity not over 20 liters") is FactSource.SCHEDULE_INFERENCE


def test_case_and_spacing_are_not_differences():
    assert source("PTO-DRIVEN   diaphragm\n pump") is FactSource.DESCRIPTION


def test_a_curly_apostrophe_is_the_same_apostrophe():
    assert fact_source("the operator’s platform",
                       "Fitted with the operator's platform.") is FactSource.DESCRIPTION


def test_a_dropped_clause_breaks_the_run():
    """The whole point of continuity: an omission changes what was said."""
    assert source("sprayer with a PTO-driven diaphragm pump") is FactSource.SCHEDULE_INFERENCE


def test_numbers_and_units_are_what_separates_two_lines_so_they_survive():
    """The earlier attempt at this measurement dropped tokens under four
    characters, which is precisely where 8-digit splits live."""
    assert source("600-liter tank") is FactSource.DESCRIPTION
    assert source("400-liter tank") is FactSource.SCHEDULE_INFERENCE


def test_a_two_word_fragment_of_the_article_name_decides_nothing():
    assert source("horticultural sprayer") is FactSource.SCHEDULE_INFERENCE


def test_a_bare_number_is_not_a_fact_either():
    assert source("600-liter") is FactSource.SCHEDULE_INFERENCE


def test_the_value_stored_is_the_string_the_column_holds():
    assert str(FactSource.DESCRIPTION) == "description"
    assert str(FactSource.SCHEDULE_INFERENCE) == "schedule_inference"
