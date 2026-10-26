"""Validation rules. A record that breaks a rule is rejected with the reasons recorded, never silently dropped."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..models import Product

MAX_PRICE = 100_000.0
MAX_TITLE = 300


def validate_product(p: Product) -> list[str]:
    errors: list[str] = []
    if not p.title:
        errors.append("missing title")
    elif len(p.title) > MAX_TITLE:
        errors.append("title too long")
    if p.price is None:
        errors.append("missing or unparseable price")
    elif p.price <= 0:
        errors.append("price must be positive")
    elif p.price > MAX_PRICE:
        errors.append("price implausibly high")
    if p.rating is not None and not 0 <= p.rating <= 5:
        errors.append("rating outside 0-5")
    if p.review_count is not None and p.review_count < 0:
        errors.append("negative review count")
    if p.stock_qty is not None and p.stock_qty < 0:
        errors.append("negative stock")
    if not p.source:
        errors.append("missing source")
    if not p.source_id:
        errors.append("missing source id")
    if not p.url.startswith(("http://", "https://")):
        errors.append("invalid url")
    return errors


@dataclass
class ValidationResult:
    valid: list[Product]
    rejected: list[tuple[Product, list[str]]] = field(default_factory=list)

    @property
    def reasons(self) -> Counter:
        return Counter(e for _p, errs in self.rejected for e in errs)


def validate_all(products: list[Product]) -> ValidationResult:
    valid, rejected = [], []
    for p in products:
        errs = validate_product(p)
        (rejected.append((p, errs)) if errs else valid.append(p))
    return ValidationResult(valid=valid, rejected=rejected)
