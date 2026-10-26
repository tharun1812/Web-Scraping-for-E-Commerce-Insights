import pytest
import requests

from ecom_insights.etl.pipeline import connect, run_pipeline
from ecom_insights.http import PoliteSession, RobotsDisallowed
from ecom_insights.scrapers import books
from tests.conftest import PAGES, PER_PAGE, detail_html, listing_html


def test_parse_listing_extracts_cards_and_next_link():
    items, nxt = books.parse_listing(listing_html(1), "http://shop.test/")
    assert len(items) == PER_PAGE and nxt == "http://shop.test/page-2.html"
    first = items[0]
    assert first.title == "Book Number 0" and first.price_text == "£10.00" and first.rating_text == "One"
    assert first.url == "http://shop.test/book_0/index.html" and "In stock" in first.availability_text
    assert books.parse_listing(listing_html(PAGES), "http://shop.test/page-3.html")[1] is None


def test_parse_detail_adds_upc_category_description_reviews():
    item = books.parse_listing(listing_html(1), "http://shop.test/")[0][2]
    books.parse_detail(detail_html(2), item)
    assert item.source_id == "upc0002" and item.category == "Fiction"
    assert item.description == "A story about number 2." and item.review_count_text == "2"
    assert item.availability_text == "In stock (7 available)"


def test_full_scrape_over_http_with_pagination_and_encoding(mock_shop):
    url, _ = mock_shop
    raw = list(books.scrape(PoliteSession(min_delay=0, retries=0), base_url=url))
    assert len(raw) == PAGES * PER_PAGE
    assert raw[0].price_text == "£10.00"                  # no mojibake despite the missing charset header
    broken = next(r for r in raw if r.title == "Book Number 5")
    assert broken.source_id == ""                         # its detail page returned 500: kept, just not enriched
    ok = next(r for r in raw if r.title == "Book Number 6")
    assert ok.source_id == "upc0006" and ok.category == "Poetry"


def test_max_pages_and_no_details(mock_shop):
    url, handler = mock_shop
    raw = list(books.scrape(PoliteSession(min_delay=0), base_url=url, max_pages=2, details=False))
    assert len(raw) == 2 * PER_PAGE
    assert not any(h.startswith("/book_") for h in handler.hits)


def test_robots_txt_is_obeyed(mock_shop):
    url, handler = mock_shop
    s = PoliteSession(min_delay=0)
    assert s.allowed(url + "page-2.html") and not s.allowed(url + "private/secret.html")
    with pytest.raises(RobotsDisallowed):
        s.get(url + "private/secret.html")
    assert "/private/secret.html" not in handler.hits
    assert PoliteSession(min_delay=0, respect_robots=False).get(url + "private/secret.html")


def test_cache_avoids_repeat_requests(mock_shop, tmp_path):
    url, handler = mock_shop
    s1 = PoliteSession(min_delay=0, cache_dir=tmp_path)
    first = s1.get(url)
    hits_after_first = len(handler.hits)
    s2 = PoliteSession(min_delay=0, cache_dir=tmp_path)
    assert s2.get(url) == first
    assert s2.cache_hits == 1 and len(handler.hits) == hits_after_first


def test_http_errors_raise(mock_shop):
    url, _ = mock_shop
    with pytest.raises(requests.HTTPError):
        PoliteSession(min_delay=0, retries=0).get(url + "missing")


def test_scrape_to_database_end_to_end(mock_shop, tmp_path):
    url, _ = mock_shop
    raw = list(books.scrape(PoliteSession(min_delay=0, retries=0), base_url=url))
    report = run_pipeline(raw, tmp_path / "t.db", tmp_path / "out", source=books.SOURCE)
    assert report.extracted == 12
    # the book with the broken detail page has no UPC, so its id falls back to its url (still unique)
    assert report.loaded == 12 and report.rejected == 0
    conn = connect(tmp_path / "t.db")
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 12
    assert conn.execute("SELECT currency FROM products LIMIT 1").fetchone()[0] == "GBP"
    assert (tmp_path / "out" / "products_clean.csv").exists()
