"""Analysis on the cleaned data: category pricing, rating/price relationship, best value, price changes, source comparison."""
from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from ..etl.dedupe import title_key


def load_products(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM products", conn)


def category_price_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Price statistics per source, currency and category (prices in different currencies are never mixed)."""
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(["source", "currency", "category"], dropna=False)["price"]
    out = g.agg(products="count", mean="mean", median="median", min="min", max="max").round(2)
    return out.reset_index().sort_values(["source", "currency", "median"], ascending=[True, True, False])


def rating_price_relationship(df: pd.DataFrame) -> float | None:
    """Spearman rank correlation between price and rating (None when there is too little data)."""
    d = df.dropna(subset=["price", "rating"])
    if len(d) < 3 or d["price"].nunique() < 2 or d["rating"].nunique() < 2:
        return None
    return round(float(d["price"].rank().corr(d["rating"].rank())), 3)


def best_value(df: pd.DataFrame, top: int = 10) -> pd.DataFrame:
    """Products rated high and priced low relative to their own category (percentile rank difference)."""
    d = df.dropna(subset=["price", "rating"]).copy()
    if d.empty:
        return d
    d["rating_pct"] = d.groupby(["currency", "category"])["rating"].rank(pct=True)
    d["price_pct"] = d.groupby(["currency", "category"])["price"].rank(pct=True)
    d["value_score"] = (d["rating_pct"] - d["price_pct"]).round(3)
    cols = ["source", "title", "category", "currency", "price", "rating", "value_score"]
    return d.sort_values(["value_score", "rating"], ascending=False).head(top)[cols]


def price_changes(conn: sqlite3.Connection) -> pd.DataFrame:
    """Products whose price differs between the two most recent runs that saw them."""
    h = pd.read_sql_query(
        "SELECT h.run_id, h.source, h.source_id, h.price, h.scraped_at, p.title FROM price_history h "
        "JOIN products p USING (source, source_id) ORDER BY h.rowid", conn)      # insertion order = run order
    if h.empty:
        return pd.DataFrame(columns=["source", "title", "old_price", "new_price", "change_pct"])
    rows = []
    for (src, sid), grp in h.groupby(["source", "source_id"]):
        if len(grp) < 2:
            continue
        old, new = grp.iloc[-2], grp.iloc[-1]
        if old["price"] != new["price"] and old["price"]:
            rows.append({"source": src, "title": new["title"], "old_price": old["price"], "new_price": new["price"],
                         "change_pct": round((new["price"] - old["price"]) / old["price"] * 100, 1)})
    return pd.DataFrame(rows, columns=["source", "title", "old_price", "new_price", "change_pct"]).sort_values(
        "change_pct", key=abs, ascending=False)


def compare_sources(df: pd.DataFrame, threshold: float = 0.88) -> pd.DataFrame:
    """Match similar product titles across different sources and compare their prices."""
    cols = ["title_a", "source_a", "price_a", "title_b", "source_b", "price_b", "currency", "similarity", "price_diff_pct", "cheaper"]
    sources = sorted(df["source"].unique()) if not df.empty else []
    rows = []
    for i, sa in enumerate(sources):
        for sb in sources[i + 1:]:
            A, B = df[df.source == sa], df[df.source == sb]
            for _, a in A.iterrows():
                ka = title_key(a["title"])
                best, best_s = None, 0.0
                for _, b in B.iterrows():
                    s = SequenceMatcher(None, ka, title_key(b["title"])).ratio()
                    if s > best_s:
                        best, best_s = b, s
                if best is None or best_s < threshold:
                    continue
                same_cur = a["currency"] == best["currency"]
                diff = round((best["price"] - a["price"]) / a["price"] * 100, 1) if same_cur and a["price"] else None
                rows.append({"title_a": a["title"], "source_a": sa, "price_a": a["price"], "title_b": best["title"],
                             "source_b": sb, "price_b": best["price"], "currency": a["currency"] if same_cur else "mixed",
                             "similarity": round(best_s, 2), "price_diff_pct": diff,
                             "cheaper": None if diff is None or diff == 0 else (sa if diff > 0 else sb)})
    return pd.DataFrame(rows, columns=cols)


def build_report(db_path: str | Path, out_dir: str | Path) -> Path:
    """Write report.md plus charts into out_dir and return the report path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    df = load_products(conn)
    runs = pd.read_sql_query("SELECT * FROM runs ORDER BY started_at", conn)
    changes = price_changes(conn)
    rejects = pd.read_sql_query("SELECT reasons, COUNT(*) AS n FROM rejects GROUP BY reasons ORDER BY n DESC", conn)
    conn.close()

    lines = ["# E-commerce insights report", ""]
    if df.empty:
        lines.append("No products in the database yet. Run a scrape first.")
        path = out / "report.md"
        path.write_text("\n".join(lines))
        return path

    lines += [f"- Products analysed: **{len(df)}** from {df['source'].nunique()} source(s)",
              f"- Pipeline runs recorded: **{len(runs)}**", ""]
    stats = category_price_stats(df)
    lines += ["## Price by category", "", stats.to_markdown(index=False), ""]
    corr = rating_price_relationship(df)
    lines += ["## Does a higher price mean a better rating?", "",
              f"Spearman correlation between price and rating: **{corr}**" if corr is not None else "Not enough rated products.", ""]
    bv = best_value(df)
    if not bv.empty:
        lines += ["## Best value (high rating, low price within the category)", "", bv.to_markdown(index=False), ""]
    if not changes.empty:
        lines += ["## Price changes since the previous run", "", changes.head(15).to_markdown(index=False), ""]
    cmp_df = compare_sources(df)
    if not cmp_df.empty:
        lines += ["## Cross-source price comparison", "", cmp_df.head(15).to_markdown(index=False), ""]
    if not rejects.empty:
        lines += ["## Records rejected by validation", "", rejects.to_markdown(index=False), ""]

    # charts (the largest-currency group only, so prices stay comparable)
    main_cur = df["currency"].mode().iloc[0] if df["currency"].notna().any() else None
    sub = df[df["currency"] == main_cur] if main_cur else df
    fig, ax = plt.subplots(figsize=(7, 4))
    groups = [g["price"].dropna().values for _, g in sub.groupby("category")]
    labels = [str(k) for k, _ in sub.groupby("category")]
    if groups:
        ax.boxplot(groups, tick_labels=labels)
    ax.set_ylabel(f"Price ({main_cur or '?'})")
    ax.set_title("Price distribution by category")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out / "price_by_category.png", dpi=130)
    plt.close(fig)

    r = sub.dropna(subset=["rating", "price"])
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(r["price"], r["rating"], alpha=0.6)
    ax.set_xlabel(f"Price ({main_cur or '?'})")
    ax.set_ylabel("Rating")
    ax.set_title("Rating vs price")
    fig.tight_layout()
    fig.savefig(out / "rating_vs_price.png", dpi=130)
    plt.close(fig)
    lines += ["## Charts", "", "![Price by category](price_by_category.png)", "", "![Rating vs price](rating_vs_price.png)", ""]

    path = out / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
