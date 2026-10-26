"""Selenium scraper for JavaScript-rendered shops (infinite "Load more" lists and lazily loaded reviews).

The browser is only used to get the page into its final state; extraction then reuses plain BeautifulSoup
parsing, which keeps the browser-dependent code small. The selectors below match the bundled demo shop
(`python -m ecom_insights demo-site`); pass your own `Selectors` for another site.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterator

from bs4 import BeautifulSoup

from ..models import RawProduct, RawReview

log = logging.getLogger(__name__)
SOURCE = "demo_dynamic_shop"
CSS = "css selector"        # == selenium.webdriver.common.by.By.CSS_SELECTOR


@dataclass(frozen=True)
class Selectors:
    card: str = ".product-card"
    load_more: str = "#load-more"
    show_reviews: str = ".show-reviews"
    review_item: str = ".reviews li"
    title: str = ".title"
    price: str = ".price"
    rating: str = ".rating"
    review_count: str = ".review-count"
    stock: str = ".stock"
    category: str = ".category"
    description: str = ".description"


def make_driver(headless: bool = True):
    """Create a Chrome driver. Needs Chrome installed; Selenium Manager downloads a matching driver."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,1600")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=opts)


def wait_until(predicate: Callable[[], bool], timeout: float = 10.0, poll: float = 0.1) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(poll)
    return predicate()


def parse_cards(html: str, base_url: str, sel: Selectors = Selectors()) -> list[RawProduct]:
    soup = BeautifulSoup(html, "html.parser")

    def text(node, css: str) -> str:
        el = node.select_one(css)
        return el.get_text(" ", strip=True) if el else ""

    products = []
    for card in soup.select(sel.card):
        rating_el = card.select_one(sel.rating)
        link = card.select_one("a[href]")
        prod = RawProduct(
            source=SOURCE,
            source_id=card.get("data-id", ""),
            title=text(card, sel.title),
            price_text=text(card, sel.price),
            rating_text=(rating_el.get("data-rating", "") if rating_el else "") or text(card, sel.rating),
            review_count_text=text(card, sel.review_count),
            availability_text=text(card, sel.stock),
            category=text(card, sel.category),
            description=text(card, sel.description),
            url=(base_url.rstrip("/") + link["href"]) if link and link["href"].startswith("/") else (link["href"] if link else ""),
        )
        for li in card.select(sel.review_item):
            r_rating = li.select_one("[data-rating]")
            prod.reviews.append(RawReview(
                text=text(li, ".text") or li.get_text(" ", strip=True),
                rating_text=r_rating.get("data-rating", "") if r_rating else "",
                author=text(li, ".author")))
        products.append(prod)
    return products


def scrape(driver, base_url: str, sel: Selectors = Selectors(), max_loads: int = 50,
           with_reviews: bool = True, timeout: float = 10.0) -> Iterator[RawProduct]:
    """Open the shop, keep pressing "Load more" until the list is complete, expand reviews, then parse."""
    driver.get(base_url)
    wait_until(lambda: len(driver.find_elements(CSS, sel.card)) > 0, timeout)

    for _ in range(max_loads):
        buttons = [b for b in driver.find_elements(CSS, sel.load_more) if b.is_displayed() and b.is_enabled()]
        if not buttons:
            break
        before = len(driver.find_elements(CSS, sel.card))
        buttons[0].click()
        if not wait_until(lambda: len(driver.find_elements(CSS, sel.card)) > before, timeout):
            log.warning("no new products appeared after clicking load more; stopping")
            break
    log.info("%d products loaded", len(driver.find_elements(CSS, sel.card)))

    if with_reviews:
        for btn in driver.find_elements(CSS, sel.show_reviews):
            try:
                btn.click()
            except Exception as exc:  # an unclickable button should not stop the run
                log.debug("could not expand reviews: %s", exc)
        wait_until(lambda: not driver.find_elements(CSS, sel.show_reviews + ":not([data-loaded])"), timeout)

    yield from parse_cards(driver.page_source, base_url, sel)
