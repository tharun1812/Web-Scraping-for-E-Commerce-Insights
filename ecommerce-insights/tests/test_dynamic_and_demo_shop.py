"""The Selenium scraper is tested with a fake browser that follows the demo shop's behaviour."""
from ecom_insights import demo_shop
from ecom_insights.etl.pipeline import run_pipeline
from ecom_insights.scrapers import dynamic
from ecom_insights.scrapers.dynamic import CSS, Selectors, parse_cards, scrape

SEL = Selectors()


def card_html(it: dict, reviews_loaded: bool) -> str:
    reviews = "".join(f'<li><span class="author">{r["author"]}</span> <span class="stars" data-rating="{r["rating"]}">*</span> '
                      f'<span class="text">{r["text"]}</span></li>' for r in it["reviews"]) if reviews_loaded else ""
    loaded = ' data-loaded="1"' if reviews_loaded else ""
    return (f'<div class="product-card" data-id="{it["id"]}"><a href="/product/{it["id"]}"><h3 class="title">{it["title"]}</h3></a>'
            f'<span class="price">{it["price"]}</span> <span class="rating" data-rating="{it["rating"]}">*</span> '
            f'<span class="review-count">{demo_shop.review_count(it)}</span><span class="stock">{it["stock"]}</span>'
            f'<span class="category">{it["category"]}</span><p class="description">{it["description"]}</p>'
            f'<button class="show-reviews"{loaded}>Show reviews</button><ul class="reviews">{reviews}</ul></div>')


class FakeElement:
    def __init__(self, on_click, displayed=True, enabled=True):
        self._on_click, self._displayed, self._enabled = on_click, displayed, enabled

    def is_displayed(self):
        return self._displayed

    def is_enabled(self):
        return self._enabled

    def click(self):
        self._on_click()


class FakeBrowser:
    """Mimics the demo shop: 12 products per 'Load more' click, reviews expand per product."""

    def __init__(self, items, page_size=12):
        self.items, self.page_size, self.shown, self.expanded = items, page_size, 0, set()
        self.url = None
        self.load_more_clicks = 0

    def get(self, url):
        self.url = url
        self.shown = self.page_size

    def _load_more(self):
        self.load_more_clicks += 1
        self.shown = min(len(self.items), self.shown + self.page_size)

    def find_elements(self, by, selector):
        assert by == CSS
        if selector == SEL.card:
            return [object()] * self.shown
        if selector == SEL.load_more:
            return [FakeElement(self._load_more)] if self.shown < len(self.items) else []
        if selector == SEL.show_reviews:
            return [FakeElement(lambda i=it["id"]: self.expanded.add(i)) for it in self.items[:self.shown]]
        if selector == SEL.show_reviews + ":not([data-loaded])":
            return [object() for it in self.items[:self.shown] if it["id"] not in self.expanded]
        return []

    @property
    def page_source(self):
        return "<html><body>" + "".join(card_html(it, it["id"] in self.expanded) for it in self.items[:self.shown]) + "</body></html>"


def test_parse_cards_reads_all_fields_and_reviews():
    it = demo_shop.build_catalogue()[0]
    raw = parse_cards(card_html(it, True), "http://shop.test")
    assert len(raw) == 1
    r = raw[0]
    assert (r.source_id, r.title, r.price_text, r.category) == (it["id"], it["title"], it["price"], it["category"])
    assert r.rating_text == str(it["rating"]) and r.availability_text == it["stock"]
    assert r.url == f"http://shop.test/product/{it['id']}" and len(r.reviews) == len(it["reviews"])


def test_scrape_clicks_load_more_until_done_then_expands_reviews():
    items = demo_shop.build_catalogue()
    browser = FakeBrowser(items)
    raw = list(scrape(browser, "http://shop.test", timeout=1))
    assert len(raw) == len(items) == 75 and browser.load_more_clicks == 6
    assert sum(len(r.reviews) for r in raw) == sum(len(i["reviews"]) for i in items)
    assert browser.url == "http://shop.test"


def test_scrape_without_reviews_skips_expansion():
    browser = FakeBrowser(demo_shop.build_catalogue())
    raw = list(scrape(browser, "http://shop.test", with_reviews=False, timeout=1))
    assert not browser.expanded and all(not r.reviews for r in raw)


def test_scrape_stops_when_load_more_makes_no_progress():
    class Stuck(FakeBrowser):
        def _load_more(self):
            self.load_more_clicks += 1          # click does nothing

    browser = Stuck(demo_shop.build_catalogue())
    raw = list(scrape(browser, "http://shop.test", timeout=0.3, with_reviews=False))
    assert len(raw) == 12 and browser.load_more_clicks == 1


def test_wait_until():
    n = {"i": 0}

    def pred():
        n["i"] += 1
        return n["i"] >= 3

    assert dynamic.wait_until(pred, timeout=1, poll=0.01) is True
    assert dynamic.wait_until(lambda: False, timeout=0.1, poll=0.01) is False


def test_browser_output_feeds_the_etl(tmp_path):
    raw = list(scrape(FakeBrowser(demo_shop.build_catalogue()), "http://shop.test", timeout=1))
    rep = run_pipeline(raw, tmp_path / "x.db", source=dynamic.SOURCE)
    assert (rep.extracted, rep.loaded, rep.rejected) == (75, 69, 3)


def test_demo_shop_api_paging_and_messy_data():
    c = demo_shop.create_demo_app().test_client()
    p1 = c.get("/api/products?page=1").get_json()
    assert len(p1["items"]) == 12 and p1["has_more"] is True
    last = c.get("/api/products?page=7").get_json()
    assert len(last["items"]) == 3 and last["has_more"] is False
    assert c.get("/api/products?page=abc").status_code == 400
    assert "reviews" in c.get("/api/products/P001/reviews").get_json()
    assert c.get("/api/products/NOPE/reviews").status_code == 404
    assert b"Allow: /" in c.get("/robots.txt").data
    assert b"load-more" in c.get("/").data and b"P001" not in c.get("/").data     # products are NOT in the HTML


def test_catalogue_is_deterministic_and_contains_the_planted_problems():
    a, b = demo_shop.build_catalogue(), demo_shop.build_catalogue()
    assert a == b and len(a) == 75
    assert sum(1 for i in a if i["price"] in ("N/A", "")) == 2
    assert len({i["id"] for i in a}) == 73                      # 2 exact duplicates share ids
