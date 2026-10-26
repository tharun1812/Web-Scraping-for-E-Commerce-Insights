"""Cleaning and normalisation: raw scraped text -> typed Product records."""
from __future__ import annotations

import re
import unicodedata

from ..models import Product, RawProduct, RawReview, Review

CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "₹": "INR", "¥": "JPY"}
CURRENCY_WORDS = {"gbp": "GBP", "usd": "USD", "eur": "EUR", "inr": "INR", "rs": "INR", "jpy": "JPY"}
WORD_NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}

MAX_REASONABLE_PRICE = 1_000_000


def fix_mojibake(text: str) -> str:
    """Repair UTF-8 text that was decoded as latin-1/cp1252 ("Â£51.77" -> "£51.77")."""
    if not text or not any(m in text for m in ("Â", "Ã", "â€")):
        return text
    for enc in ("cp1252", "latin-1"):
        try:
            fixed = text.encode(enc).decode("utf-8")
            return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", fix_mojibake(text))
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_price(text: str | None) -> tuple[float | None, str | None]:
    """'£51.77' -> (51.77, 'GBP'); '1.299,00 €' -> (1299.0, 'EUR'); 'free' -> (None, None)."""
    text = normalize_text(text)
    if not text:
        return None, None
    currency = next((code for sym, code in CURRENCY_SYMBOLS.items() if sym in text), None)
    if currency is None:
        word = re.search(r"\b(gbp|usd|eur|inr|rs|jpy)\b\.?", text.lower())
        currency = CURRENCY_WORDS[word.group(1)] if word else None
    m = re.search(r"\d[\d.,]*", text)
    if not m:
        return None, currency
    num = m.group(0).rstrip(".,")
    has_dot, has_comma = "." in num, "," in num
    if has_dot and has_comma:
        decimal = "." if num.rfind(".") > num.rfind(",") else ","
        thousands = "," if decimal == "." else "."
        num = num.replace(thousands, "").replace(decimal, ".")
    elif has_comma:
        # "12,50" is a decimal comma; "1,299" or "1,299,000" are thousands separators
        num = num.replace(",", ".") if re.fullmatch(r"\d+,\d{1,2}", num) else num.replace(",", "")
    elif num.count(".") > 1:
        num = num.replace(".", "")
    try:
        value = float(num)
    except ValueError:
        return None, currency
    if "-" in text[:m.start()]:      # "$-4.00" / "-$4": keep the sign so validation can reject it
        value = -value
    return round(value, 2), currency


def parse_rating(text: str | None) -> float | None:
    """'Three' -> 3.0, '4 out of 5' -> 4.0, '4.5' -> 4.5; anything outside 0-5 -> None."""
    text = normalize_text(text).lower()
    if not text:
        return None
    for word, n in WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", text):
            return float(n)
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        return None
    value = float(m.group(0))
    return value if 0 <= value <= 5 else None


def parse_int(text: str | None) -> int | None:
    text = normalize_text(text).replace(",", "")
    m = re.search(r"\d+", text)
    return int(m.group(0)) if m else None


def parse_availability(text: str | None) -> tuple[bool | None, int | None]:
    """'In stock (22 available)' -> (True, 22); 'Out of stock' -> (False, 0)."""
    t = normalize_text(text).lower()
    if not t:
        return None, None
    if "out of stock" in t or "sold out" in t or "unavailable" in t:
        return False, 0
    qty = parse_int(t)
    if "in stock" in t or "available" in t or "left" in t:
        return True, qty
    return None, qty


def clean_review(raw: RawReview) -> Review | None:
    text = normalize_text(raw.text)
    if not text:
        return None
    return Review(text=text, rating=parse_rating(raw.rating_text), author=normalize_text(raw.author))


def clean_product(raw: RawProduct) -> Product:
    """Convert one raw record into a typed Product. Never raises: unparseable fields become None."""
    price, currency = parse_price(raw.price_text)
    in_stock, qty = parse_availability(raw.availability_text)
    reviews = [r for r in (clean_review(x) for x in raw.reviews) if r is not None]
    review_count = parse_int(raw.review_count_text)
    if review_count is None and reviews:
        review_count = len(reviews)
    category = normalize_text(raw.category)
    return Product(
        source=normalize_text(raw.source).lower(),
        source_id=normalize_text(raw.source_id) or normalize_text(raw.url),
        title=normalize_text(raw.title),
        price=price, currency=currency,
        rating=parse_rating(raw.rating_text),
        review_count=review_count,
        in_stock=in_stock, stock_qty=qty,
        category=category.title() if category.islower() else category,
        url=normalize_text(raw.url),
        description=normalize_text(raw.description),
        image_url=normalize_text(raw.image_url),
        scraped_at=raw.scraped_at,
        reviews=reviews,
    )
