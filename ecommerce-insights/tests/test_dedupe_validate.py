from ecom_insights.etl.dedupe import deduplicate, title_key
from ecom_insights.etl.validate import validate_all, validate_product
from ecom_insights.models import Product


def prod(sid="1", title="Mug", price=9.5, source="s", **kw):
    base = dict(source=source, source_id=sid, title=title, price=price, currency="USD", rating=None, review_count=None,
                in_stock=None, stock_qty=None, category="", url="http://x/" + sid, description="", image_url="",
                scraped_at="2026-01-01T00:00:00+00:00")
    base.update(kw)
    return Product(**base)


def test_title_key_ignores_case_punctuation_and_spacing():
    assert title_key("  Red-Mug!! ") == title_key("red mug")


def test_exact_duplicates_keep_the_most_complete_copy():
    a, b = prod("1"), prod("1", rating=4.0, category="Home")
    res = deduplicate([a, b])
    assert res.exact_removed == 1 and res.kept == [b]


def test_exact_tie_keeps_the_newer_scrape():
    old, new = prod("1", scraped_at="2026-01-01T00:00:00+00:00"), prod("1", scraped_at="2026-02-01T00:00:00+00:00")
    assert deduplicate([old, new]).kept == [new]


def test_near_duplicates_same_title_and_price_different_id():
    res = deduplicate([prod("1", "Red Mug"), prod("2", "red  mug"), prod("3", "Red Mug", price=12.0)])
    assert res.near_removed == 1 and res.exact_removed == 0
    assert {p.source_id for p in res.kept} == {"1", "3"}       # equal completeness: the first copy wins


def test_same_title_on_different_sources_is_not_a_duplicate():
    assert len(deduplicate([prod("1", source="a"), prod("1", source="b")]).kept) == 2


def test_validation_rules():
    assert validate_product(prod()) == []
    assert "missing title" in validate_product(prod(title=""))
    assert "missing or unparseable price" in validate_product(prod(price=None))
    assert "price must be positive" in validate_product(prod(price=-1))
    assert "price implausibly high" in validate_product(prod(price=10**7))
    assert "rating outside 0-5" in validate_product(prod(rating=7))
    assert "invalid url" in validate_product(prod(url="ftp://x"))
    assert "missing source id" in validate_product(prod(sid=""))


def test_validate_all_splits_and_counts_reasons():
    res = validate_all([prod("1"), prod("2", price=None), prod("3", price=None, title="")])
    assert len(res.valid) == 1 and len(res.rejected) == 2
    assert res.reasons["missing or unparseable price"] == 2 and res.reasons["missing title"] == 1
