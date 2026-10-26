"""A small JavaScript-rendered shop used to demonstrate and test the Selenium scraper.

The HTML page contains no products; they are fetched from a JSON API by JavaScript when "Load more" is clicked,
and reviews load lazily per product, like many real shops. The catalogue is generated with a fixed seed and
deliberately contains messy data (duplicates, missing prices, odd formats) for the ETL pipeline to handle.
"""
from __future__ import annotations

import random

from .models import RawProduct, RawReview, utc_now

CATEGORIES = {
    "Electronics": (["Wireless", "Portable", "Smart", "Compact", "Pro"], ["Speaker", "Headphones", "Charger", "Webcam", "Keyboard", "Router"], (19, 420)),
    "Home": (["Ceramic", "Bamboo", "Glass", "Steel", "Linen"], ["Mug Set", "Cutting Board", "Lamp", "Organizer", "Throw Blanket"], (8, 140)),
    "Sports": (["Trail", "Lightweight", "Pro", "Insulated", "Foldable"], ["Water Bottle", "Yoga Mat", "Backpack", "Resistance Bands", "Jump Rope"], (6, 120)),
    "Toys": (["Classic", "Wooden", "Magnetic", "Giant", "Mini"], ["Puzzle", "Building Set", "Board Game", "Race Track", "Plush Bear"], (5, 90)),
}
REVIEW_TEXTS = ["Great value for the price.", "Works as described.", "Stopped working after a month.",
                "Exactly what I needed, fast delivery.", "Build quality is poor.", "Love it, would buy again.",
                "Average, nothing special.", "Arrived damaged but support replaced it."]
AUTHORS = ["Asha", "Ben", "Chen", "Dana", "Eli", "Farah", "Gus", "Hana"]


def build_catalogue(n: int = 72, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    items: list[dict] = []
    for i in range(n):
        cat = rng.choice(list(CATEGORIES))
        adjs, nouns, (lo, hi) = CATEGORIES[cat]
        price = round(rng.uniform(lo, hi), 2)
        qty = rng.choice([0, 0, 3, 8, 15, 40])
        items.append({
            "id": f"P{i + 1:03d}",
            "title": f"{rng.choice(adjs)} {rng.choice(nouns)}",
            "price": f"${price:,.2f}",
            "rating": round(min(5, max(1, 2.5 + (price / hi) * 1.2 + rng.uniform(-1.2, 1.2))), 1),
            "category": cat,
            "stock": "Out of stock" if qty == 0 else f"In stock ({qty} available)",
            "description": f"A {cat.lower()} essential with a one-year warranty.",
            "reviews": [{"author": rng.choice(AUTHORS), "rating": rng.randint(1, 5), "text": rng.choice(REVIEW_TEXTS)}
                        for _ in range(rng.choice([0, 1, 2, 3, 4]))],
        })
    # ---- deliberate mess for the ETL stage ----
    items[5]["price"] = "N/A"                       # missing price
    items[17]["price"] = ""                         # missing price
    items[30]["price"] = "$-4.00"                   # impossible price
    items[22]["rating"] = 9.5                       # impossible rating
    items[40]["title"] = "  " + items[40]["title"].upper() + "   "      # whitespace and casing noise
    items[9]["price"] = "€" + items[9]["price"][1:].replace(",", "")    # different currency
    items.append(dict(items[3]))                                        # exact duplicate (same id)
    items.append(dict(items[11]))                                       # exact duplicate (same id)
    dup = dict(items[7])                                                # near duplicate: same listing, new id
    dup.update(id="P900", title=items[7]["title"].lower())
    items.append(dup)
    return items


def review_count(item: dict) -> str:
    n = len(item["reviews"])
    return f"{n} review{'s' if n != 1 else ''}"


def catalogue_as_raw(n: int = 72, seed: int = 42) -> list[RawProduct]:
    """What the browser scraper would collect, without needing a browser (used for the offline demo)."""
    now = utc_now()
    return [RawProduct(
        source="demo_dynamic_shop", source_id=it["id"], title=it["title"], price_text=it["price"],
        rating_text=str(it["rating"]), review_count_text=review_count(it), availability_text=it["stock"],
        category=it["category"], description=it["description"], url=f"http://localhost:8000/product/{it['id']}",
        scraped_at=now, reviews=[RawReview(text=r["text"], rating_text=str(r["rating"]), author=r["author"]) for r in it["reviews"]],
    ) for it in build_catalogue(n, seed)]


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Demo Shop</title>
<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}
.product-card{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:.75rem 0}
.price{font-weight:700}.reviews{color:#444}button{padding:.4rem .8rem}</style></head>
<body><h1>Demo Shop</h1><p>Products load with JavaScript.</p>
<div id="products"></div>
<button id="load-more" type="button">Load more</button>
<script>
let page = 1;
const list = document.getElementById('products');
const more = document.getElementById('load-more');

function stars(r) { return r == null ? '' : '\\u2605'.repeat(Math.round(r)); }

function card(p) {
  const el = document.createElement('div');
  el.className = 'product-card';
  el.dataset.id = p.id;
  el.innerHTML =
    '<a href="/product/' + p.id + '"><h3 class="title"></h3></a>' +
    '<span class="price"></span> ' +
    '<span class="rating"></span> <span class="review-count"></span><br>' +
    '<span class="stock"></span> | <span class="category"></span>' +
    '<p class="description"></p>' +
    '<button class="show-reviews" type="button">Show reviews</button><ul class="reviews"></ul>';
  el.querySelector('.title').textContent = p.title;
  el.querySelector('.price').textContent = p.price;
  const rating = el.querySelector('.rating');
  rating.dataset.rating = p.rating == null ? '' : p.rating;
  rating.textContent = stars(p.rating);
  el.querySelector('.review-count').textContent = p.review_count;
  el.querySelector('.stock').textContent = p.stock;
  el.querySelector('.category').textContent = p.category;
  el.querySelector('.description').textContent = p.description;
  el.querySelector('.show-reviews').addEventListener('click', (ev) => loadReviews(p.id, el, ev.target));
  return el;
}

async function loadMore() {
  more.disabled = true;
  const res = await fetch('/api/products?page=' + page);
  const data = await res.json();
  setTimeout(() => {                       // small delay, like a real network round trip
    data.items.forEach((p) => list.appendChild(card(p)));
    page += 1;
    more.disabled = false;
    if (!data.has_more) more.style.display = 'none';
  }, 150);
}

async function loadReviews(id, el, btn) {
  if (btn.dataset.loaded) return;
  const res = await fetch('/api/products/' + id + '/reviews');
  const data = await res.json();
  const ul = el.querySelector('.reviews');
  data.reviews.forEach((r) => {
    const li = document.createElement('li');
    li.innerHTML = '<span class="author"></span> <span class="stars"></span> <span class="text"></span>';
    li.querySelector('.author').textContent = r.author;
    const s = li.querySelector('.stars');
    s.dataset.rating = r.rating;
    s.textContent = stars(r.rating);
    li.querySelector('.text').textContent = r.text;
    ul.appendChild(li);
  });
  btn.dataset.loaded = '1';
}

more.addEventListener('click', loadMore);
loadMore();
</script></body></html>
"""


def create_demo_app(n: int = 72, seed: int = 42, page_size: int = 12):
    from flask import Flask, Response, abort, jsonify, request

    app = Flask(__name__)
    catalogue = build_catalogue(n, seed)
    by_id = {it["id"]: it for it in catalogue}

    @app.get("/")
    def index():
        return PAGE

    @app.get("/robots.txt")
    def robots():
        return Response("User-agent: *\nAllow: /\n", mimetype="text/plain")

    @app.get("/api/products")
    def products():
        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            abort(400)
        chunk = catalogue[(page - 1) * page_size: page * page_size]
        return jsonify({
            "items": [{**{k: it[k] for k in ("id", "title", "price", "rating", "category", "stock", "description")},
                       "review_count": review_count(it)} for it in chunk],
            "has_more": page * page_size < len(catalogue),
        })

    @app.get("/api/products/<pid>/reviews")
    def reviews(pid: str):
        if pid not in by_id:
            abort(404)
        return jsonify({"reviews": by_id[pid]["reviews"]})

    @app.get("/product/<pid>")
    def product_page(pid: str):
        if pid not in by_id:
            abort(404)
        return f"<h1>{by_id[pid]['title']}</h1>"

    return app
