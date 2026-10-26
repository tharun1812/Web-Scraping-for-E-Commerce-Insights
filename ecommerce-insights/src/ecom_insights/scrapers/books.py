"""Static-HTML scraper (BeautifulSoup) for books.toscrape.com, a sandbox site built for scraping practice."""
from __future__ import annotations

import logging
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import PoliteSession
from ..models import RawProduct

log = logging.getLogger(__name__)
DEFAULT_BASE_URL = "https://books.toscrape.com/"
SOURCE = "books_toscrape"


def parse_listing(html: str, page_url: str) -> tuple[list[RawProduct], str | None]:
    """Products on one listing page plus the URL of the next page (None on the last page)."""
    soup = BeautifulSoup(html, "html.parser")
    products: list[RawProduct] = []
    for card in soup.select("article.product_pod"):
        link = card.select_one("h3 a")
        if link is None:
            continue
        rating_el = card.select_one("p.star-rating")
        rating_classes = [c for c in (rating_el.get("class") or []) if c != "star-rating"] if rating_el else []
        img = card.select_one("img")
        avail = card.select_one("p.availability")
        price = card.select_one("p.price_color")
        products.append(RawProduct(
            source=SOURCE,
            title=link.get("title") or link.get_text(strip=True),
            url=urljoin(page_url, link.get("href", "")),
            price_text=price.get_text(strip=True) if price else "",
            rating_text=rating_classes[0] if rating_classes else "",
            availability_text=avail.get_text(" ", strip=True) if avail else "",
            image_url=urljoin(page_url, img.get("src", "")) if img else "",
        ))
    nxt = soup.select_one("li.next a")
    return products, urljoin(page_url, nxt["href"]) if nxt and nxt.get("href") else None


def parse_detail(html: str, product: RawProduct) -> RawProduct:
    """Add the fields that only exist on the product page: id (UPC), category, description, reviews count."""
    soup = BeautifulSoup(html, "html.parser")
    table = {th.get_text(strip=True): td.get_text(" ", strip=True)
             for th in soup.select("table.table-striped th") for td in [th.find_next_sibling("td")] if td}
    crumbs = [li.get_text(strip=True) for li in soup.select("ul.breadcrumb li")]
    desc_header = soup.select_one("#product_description")
    desc = desc_header.find_next_sibling("p") if desc_header else None
    product.source_id = table.get("UPC", product.source_id)
    product.category = crumbs[2] if len(crumbs) >= 3 else product.category
    product.description = desc.get_text(" ", strip=True) if desc else product.description
    product.review_count_text = table.get("Number of reviews", product.review_count_text)
    product.availability_text = table.get("Availability", product.availability_text)
    if not product.price_text:
        product.price_text = table.get("Price (incl. tax)", "")
    return product


def scrape(session: PoliteSession, base_url: str = DEFAULT_BASE_URL, max_pages: int | None = None,
           details: bool = True) -> Iterator[RawProduct]:
    """Walk the listing pages (and optionally every product page), yielding raw products."""
    url: str | None = base_url
    page = 0
    while url and (max_pages is None or page < max_pages):
        page += 1
        try:
            items, url_next = parse_listing(session.get(url), url)
        except Exception as exc:  # one bad page must not abort the whole run
            log.warning("listing page failed (%s): %s", url, exc)
            break
        log.info("page %d: %d products", page, len(items))
        for item in items:
            if details:
                try:
                    parse_detail(session.get(item.url), item)
                except Exception as exc:
                    log.warning("detail page failed (%s): %s", item.url, exc)
            yield item
        url = url_next
