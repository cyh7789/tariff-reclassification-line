"""Reading a catalog export, which is how anyone gets their own work into this.

The interesting cases are all about what a real export looks like: the columns
are named whatever the ERP calls them, a byte-order mark leads the file, and some
lines have never been classified at all. That last one is not a broken row. A
broker's inbox is mostly lines nobody has filed before, and turning them away at
the door would make the import feature useless for the work it exists for.
"""

import pytest

from fastapi import HTTPException

from fleet.app.main import read_catalog_csv


def csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def test_a_line_with_no_filed_code_is_accepted_and_carries_no_code_forward():
    rows = read_catalog_csv(csv_bytes(
        "sku,description,hts\n"
        "NEW-1,a cordless impact wrench,\n"
        "OLD-1,a horticultural sprayer,8424.41\n"))

    assert [r["item_id"] for r in rows] == ["NEW-1", "OLD-1"]
    assert rows[0]["prior_code"] == ""
    assert rows[1]["prior_code"] == "842441"


def test_a_file_without_a_code_column_at_all_still_imports():
    """A new product list is exactly this: items and what they are."""
    rows = read_catalog_csv(csv_bytes("item,goods\nX-9,a stainless steel thermos\n"))

    assert rows == [{"item_id": "X-9", "prior_code": "", "description": "a stainless steel thermos"}]


def test_half_a_code_is_dropped_rather_than_looked_up():
    """Four digits cannot be found in a table keyed by subheading, and passing it
    on would send triage hunting for a heading nobody filed."""
    rows = read_catalog_csv(csv_bytes("sku,description,hts\nA-1,a garden hose,8424\n"))

    assert rows[0]["prior_code"] == ""


def test_a_row_missing_the_description_is_the_one_that_gets_skipped():
    rows = read_catalog_csv(csv_bytes(
        "sku,description,hts\nA-1,,842441\nA-2,a sprayer,842441\n"))

    assert [r["item_id"] for r in rows] == ["A-2"]


def test_a_file_with_no_description_column_is_refused_by_name():
    with pytest.raises(HTTPException) as exc:
        read_catalog_csv(csv_bytes("sku,hts\nA-1,842441\n"))

    assert "description" in exc.value.detail


def test_a_byte_order_mark_does_not_hide_the_first_column():
    rows = read_catalog_csv("﻿sku,description\nA-1,a sprayer\n".encode("utf-8"))

    assert rows[0]["item_id"] == "A-1"
