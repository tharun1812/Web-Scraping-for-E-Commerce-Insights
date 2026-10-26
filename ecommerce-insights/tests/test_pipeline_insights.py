import json
import sqlite3

import pandas as pd

from ecom_insights.analysis import insights
from ecom_insights.demo_shop import catalogue_as_raw
from ecom_insights.etl.pipeline import connect, run_pipeline
from ecom_insights.models import RawProduct, RawReview


def raw(sid, title, price, rating="4", cat="Home", source="a"):
    return RawProduct(source=source, source_id=sid, title=title, price_text=price, rating_text=rating, category=cat,
                      availability_text="In stock (3 available)", url=f"http://x/{sid}")


def test_demo_catalogue_goes_through_every_stage(tmp_path):
    rep = run_pipeline(catalogue_as_raw(), tmp_path / "d.db", tmp_path / "out", source="demo")
    assert rep.extracted == 75 and rep.exact_duplicates_removed == 2 and rep.near_duplicates_removed == 1
    assert rep.rejected == 3 and rep.loaded == 69
    assert rep.reject_reasons == {"missing or unparseable price": 2, "price must be positive": 1}
    assert rep.extracted - rep.exact_duplicates_removed - rep.near_duplicates_removed - rep.rejected == rep.loaded
    saved = json.loads(next((tmp_path / "out").glob("quality_report_*.json")).read_text())
    assert saved["loaded"] == 69
    assert (tmp_path / "out" / "rejected.csv").read_text().count("\n") == 4          # header + 3 rows


def test_rerun_records_price_history_and_is_idempotent(tmp_path):
    db = tmp_path / "h.db"
    run_pipeline([raw("1", "Mug", "$10.00"), raw("2", "Lamp", "$20.00")], db)
    run_pipeline([raw("1", "Mug", "$12.50"), raw("2", "Lamp", "$20.00")], db)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2          # upserted, not duplicated
    assert conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 4
    ch = insights.price_changes(conn)
    assert len(ch) == 1 and ch.iloc[0]["title"] == "Mug" and ch.iloc[0]["change_pct"] == 25.0


def test_reviews_replaced_on_rerun(tmp_path):
    db = tmp_path / "r.db"
    a = raw("1", "Mug", "$10")
    a.reviews = [RawReview("good", "5"), RawReview("bad", "1")]
    run_pipeline([a], db)
    b = raw("1", "Mug", "$10")
    b.reviews = [RawReview("fine", "3")]
    run_pipeline([b], db)
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1


def df_of(rows):
    return pd.DataFrame(rows, columns=["source", "title", "category", "currency", "price", "rating"])


def test_category_stats_never_mix_currencies():
    df = df_of([("a", "x", "Home", "USD", 10, 4), ("a", "y", "Home", "USD", 20, 5), ("a", "z", "Home", "EUR", 99, 3)])
    stats = insights.category_price_stats(df)
    assert len(stats) == 2
    usd = stats[stats.currency == "USD"].iloc[0]
    assert usd["products"] == 2 and usd["median"] == 15.0


def test_rating_price_relationship():
    up = df_of([("a", str(i), "H", "USD", i, i) for i in range(1, 8)])
    assert insights.rating_price_relationship(up) == 1.0
    assert insights.rating_price_relationship(up.assign(rating=lambda d: 8 - d.rating)) == -1.0
    assert insights.rating_price_relationship(up.head(2)) is None


def test_best_value_prefers_cheap_and_well_rated_within_category():
    df = df_of([("a", "cheap-good", "H", "USD", 5, 5), ("a", "pricey-bad", "H", "USD", 50, 2), ("a", "mid", "H", "USD", 20, 3)])
    assert insights.best_value(df).iloc[0]["title"] == "cheap-good"


def test_compare_sources_matches_similar_titles_and_flags_cheaper():
    df = df_of([("a", "Wireless Speaker", "E", "USD", 100, 4), ("b", "wireless speaker!", "E", "USD", 80, 4),
                ("b", "Garden Hose", "G", "USD", 15, 3), ("a", "Quantum Toaster", "H", "EUR", 50, 3),
                ("b", "Quantum Toaster", "H", "USD", 55, 3)])
    out = insights.compare_sources(df)
    spk = out[out.title_a == "Wireless Speaker"].iloc[0]
    assert spk["price_diff_pct"] == -20.0 and spk["cheaper"] == "b"
    mixed = out[out.title_a == "Quantum Toaster"].iloc[0]
    assert mixed["currency"] == "mixed" and pd.isna(mixed["price_diff_pct"])      # no price maths across currencies
    assert "Garden Hose" not in set(out.title_b)


def test_build_report_creates_markdown_and_charts(tmp_path):
    run_pipeline(catalogue_as_raw(), tmp_path / "d.db")
    path = insights.build_report(tmp_path / "d.db", tmp_path / "rep")
    text = path.read_text()
    assert "## Price by category" in text and "Spearman" in text and "Records rejected" in text
    assert (tmp_path / "rep" / "price_by_category.png").stat().st_size > 1000
    assert (tmp_path / "rep" / "rating_vs_price.png").stat().st_size > 1000


def test_build_report_on_empty_database(tmp_path):
    connect(tmp_path / "e.db").close()
    assert "No products" in insights.build_report(tmp_path / "e.db", tmp_path / "rep").read_text()
