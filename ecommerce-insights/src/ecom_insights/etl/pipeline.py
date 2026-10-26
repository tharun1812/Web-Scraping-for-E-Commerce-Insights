"""Extract -> Transform -> Validate -> Load. Each stage reports how many records it kept and why others left."""
from __future__ import annotations

import csv
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from ..models import Product, RawProduct, utc_now
from .clean import clean_product
from .dedupe import deduplicate
from .validate import validate_all

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, started_at TEXT, source TEXT, raw_count INTEGER, loaded INTEGER);
CREATE TABLE IF NOT EXISTS products (
    source TEXT, source_id TEXT, title TEXT, price REAL, currency TEXT, rating REAL, review_count INTEGER,
    in_stock INTEGER, stock_qty INTEGER, category TEXT, url TEXT, description TEXT, image_url TEXT,
    scraped_at TEXT, PRIMARY KEY (source, source_id));
CREATE TABLE IF NOT EXISTS price_history (
    run_id TEXT, source TEXT, source_id TEXT, scraped_at TEXT, price REAL, in_stock INTEGER,
    PRIMARY KEY (run_id, source, source_id));
CREATE TABLE IF NOT EXISTS reviews (source TEXT, source_id TEXT, run_id TEXT, author TEXT, rating REAL, text TEXT);
CREATE TABLE IF NOT EXISTS rejects (run_id TEXT, source TEXT, source_id TEXT, reasons TEXT, title TEXT, price REAL);
"""


@dataclass
class PipelineReport:
    run_id: str
    source: str
    extracted: int
    cleaned: int
    exact_duplicates_removed: int
    near_duplicates_removed: int
    rejected: int
    loaded: int
    reject_reasons: dict[str, int]

    def to_dict(self) -> dict:
        return asdict(self)


def connect(db_path: str | Path) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    return conn


def run_pipeline(raw: Iterable[RawProduct], db_path: str | Path, out_dir: str | Path | None = None,
                 source: str = "mixed") -> PipelineReport:
    raw_list = list(raw)
    run_id = uuid.uuid4().hex[:8]

    cleaned = [clean_product(r) for r in raw_list]                       # Transform
    deduped = deduplicate(cleaned)                                       # De-duplicate
    checked = validate_all(deduped.kept)                                 # Validate

    conn = connect(db_path)                                              # Load
    with conn:
        for p in checked.valid:
            conn.execute("INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (p.source, p.source_id, p.title, p.price, p.currency, p.rating, p.review_count,
                          None if p.in_stock is None else int(p.in_stock), p.stock_qty, p.category, p.url,
                          p.description, p.image_url, p.scraped_at))
            conn.execute("INSERT OR REPLACE INTO price_history VALUES (?,?,?,?,?,?)",
                         (run_id, p.source, p.source_id, p.scraped_at, p.price,
                          None if p.in_stock is None else int(p.in_stock)))
            conn.execute("DELETE FROM reviews WHERE source=? AND source_id=?", (p.source, p.source_id))
            conn.executemany("INSERT INTO reviews VALUES (?,?,?,?,?,?)",
                             [(p.source, p.source_id, run_id, r.author, r.rating, r.text) for r in p.reviews])
        for p, errs in checked.rejected:
            conn.execute("INSERT INTO rejects VALUES (?,?,?,?,?,?)",
                         (run_id, p.source, p.source_id, "; ".join(errs), p.title, p.price))
        conn.execute("INSERT INTO runs VALUES (?,?,?,?,?)", (run_id, utc_now(), source, len(raw_list), len(checked.valid)))
    conn.close()

    report = PipelineReport(
        run_id=run_id, source=source, extracted=len(raw_list), cleaned=len(cleaned),
        exact_duplicates_removed=deduped.exact_removed, near_duplicates_removed=deduped.near_removed,
        rejected=len(checked.rejected), loaded=len(checked.valid), reject_reasons=dict(checked.reasons))
    if out_dir:
        _export(out_dir, checked.valid, checked.rejected, report)
    return report


def _export(out_dir: str | Path, valid: list[Product], rejected, report: PipelineReport) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if valid:
        rows = [p.to_row() for p in valid]
        with open(out / "products_clean.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    with open(out / "rejected.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "source_id", "title", "price", "reasons"])
        for p, errs in rejected:
            w.writerow([p.source, p.source_id, p.title, p.price, "; ".join(errs)])
    (out / f"quality_report_{report.run_id}.json").write_text(json.dumps(report.to_dict(), indent=2))
