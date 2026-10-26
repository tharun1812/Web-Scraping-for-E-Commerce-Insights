"""Data containers for each pipeline stage: raw (as scraped, all text) -> clean (typed)."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class RawReview:
    text: str = ""
    rating_text: str = ""
    author: str = ""


@dataclass
class RawProduct:
    """Exactly what the scraper saw. Nothing is cleaned or converted yet."""
    source: str
    source_id: str = ""
    title: str = ""
    price_text: str = ""
    rating_text: str = ""
    review_count_text: str = ""
    availability_text: str = ""
    category: str = ""
    url: str = ""
    description: str = ""
    image_url: str = ""
    scraped_at: str = field(default_factory=utc_now)
    reviews: list[RawReview] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Review:
    text: str
    rating: float | None = None
    author: str = ""


@dataclass
class Product:
    """Typed, normalised product record."""
    source: str
    source_id: str
    title: str
    price: float | None
    currency: str | None
    rating: float | None
    review_count: int | None
    in_stock: bool | None
    stock_qty: int | None
    category: str
    url: str
    description: str
    image_url: str
    scraped_at: str
    reviews: list[Review] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.source_id)

    def to_row(self) -> dict:
        d = asdict(self)
        d.pop("reviews")
        d["review_texts"] = len(self.reviews)
        return d
