import pytest

from ecom_insights.etl.clean import (clean_product, fix_mojibake, normalize_text, parse_availability, parse_int,
                                     parse_price, parse_rating)
from ecom_insights.models import RawProduct, RawReview


@pytest.mark.parametrize("text,expected", [
    ("£51.77", (51.77, "GBP")), ("Â£51.77", (51.77, "GBP")), ("$1,299.00", (1299.0, "USD")),
    ("12,50 €", (12.5, "EUR")), ("1.299,00 €", (1299.0, "EUR")), ("USD 20", (20.0, "USD")),
    ("Rs. 1,200", (1200.0, "INR")), ("₹ 499", (499.0, "INR")), ("1,299,000", (1299000.0, None)),
    ("$-4.00", (-4.0, "USD")), ("free", (None, None)), ("", (None, None)), (None, (None, None)),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Three", 3.0), ("star-rating Five", 5.0), ("4 out of 5", 4.0), ("4.5", 4.5), ("0", 0.0),
    ("9", None), ("", None), ("great", None), (None, None),
])
def test_parse_rating(text, expected):
    assert parse_rating(text) == expected


def test_parse_availability_and_int():
    assert parse_availability("In stock (22 available)") == (True, 22)
    assert parse_availability("Out of stock") == (False, 0)
    assert parse_availability("Only 3 left") == (True, 3)
    assert parse_availability("") == (None, None)
    assert parse_int("12 reviews") == 12 and parse_int("1,204 ratings") == 1204 and parse_int("none") is None


def test_text_normalisation_and_mojibake():
    assert normalize_text("  Hello \n\t  World\u200b ") == "Hello World"
    assert normalize_text("ＡＢＣ") == "ABC"
    assert fix_mojibake("Â£5") == "£5" and fix_mojibake("plain") == "plain"
    assert normalize_text(None) == ""


def test_clean_product_converts_everything():
    raw = RawProduct(source="Shop", source_id=" 42 ", title="  Red   Mug ", price_text="Â£9.50", rating_text="Four",
                     review_count_text="", availability_text="In stock (7 available)", category="home goods",
                     url="http://x/1", reviews=[RawReview("  nice  ", "5", " Ann "), RawReview("   ", "3")])
    p = clean_product(raw)
    assert (p.source, p.source_id, p.title) == ("shop", "42", "Red Mug")
    assert (p.price, p.currency, p.rating) == (9.5, "GBP", 4.0)
    assert (p.in_stock, p.stock_qty, p.category) == (True, 7, "Home Goods")
    assert [r.text for r in p.reviews] == ["nice"] and p.reviews[0].author == "Ann"
    assert p.review_count == 1                      # inferred from the scraped reviews


def test_clean_product_never_raises_on_garbage():
    p = clean_product(RawProduct(source="x", title="", price_text="???", rating_text="@@"))
    assert p.price is None and p.rating is None and p.title == ""
