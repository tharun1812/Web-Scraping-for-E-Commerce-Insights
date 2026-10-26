"""Duplicate removal: exact (same source + id) and near-duplicate (same source, same normalised title and price)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Product


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()


def completeness(p: Product) -> int:
    """How many optional fields are filled in: used to keep the best copy of a duplicate."""
    return sum(v not in (None, "", []) for v in (p.price, p.rating, p.review_count, p.in_stock, p.category,
                                                  p.description, p.image_url)) + len(p.reviews)


@dataclass
class DedupeResult:
    kept: list[Product]
    exact_removed: int = 0
    near_removed: int = 0
    dropped: list[tuple[Product, str]] = field(default_factory=list)


def deduplicate(products: list[Product]) -> DedupeResult:
    # 1) exact duplicates: same (source, source_id) -> keep the most complete, newest copy
    by_key: dict[tuple[str, str], Product] = {}
    dropped: list[tuple[Product, str]] = []
    for p in products:
        cur = by_key.get(p.key)
        if cur is None:
            by_key[p.key] = p
            continue
        winner, loser = (p, cur) if (completeness(p), p.scraped_at) > (completeness(cur), cur.scraped_at) else (cur, p)
        by_key[p.key] = winner
        dropped.append((loser, "exact duplicate"))
    exact = len(dropped)

    # 2) near duplicates: same listing re-posted under another id (same normalised title and price)
    seen: dict[tuple[str, str, float | None], Product] = {}
    for p in by_key.values():
        k = (p.source, title_key(p.title), p.price)
        if not k[1]:
            seen[(p.source, f"__id_{p.source_id}", p.price)] = p
            continue
        cur = seen.get(k)
        if cur is None:
            seen[k] = p
            continue
        winner, loser = (p, cur) if completeness(p) > completeness(cur) else (cur, p)
        seen[k] = winner
        dropped.append((loser, "near duplicate (same title and price)"))
    kept = list(seen.values())
    return DedupeResult(kept=kept, exact_removed=exact, near_removed=len(dropped) - exact, dropped=dropped)
