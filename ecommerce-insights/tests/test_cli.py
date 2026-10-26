"""The command line interface, exercised the way a user runs it."""
import json
import sqlite3

import pytest

from ecom_insights import cli
from ecom_insights.scrapers import dynamic


def run(*args, capsys):
    code = cli.main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_demo_command_builds_database_report_and_charts(tmp_path, capsys):
    code, out, _ = run("demo", "--db", str(tmp_path / "d.db"), "--out", str(tmp_path / "o"), capsys=capsys)
    assert code == 0 and '"loaded": 69' in out and "Report:" in out
    assert (tmp_path / "o" / "report.md").exists() and (tmp_path / "o" / "rejected.csv").exists()


def test_scrape_books_then_report_over_http(mock_shop, tmp_path, capsys):
    url, _ = mock_shop
    db, out_dir, cache = str(tmp_path / "s.db"), str(tmp_path / "o"), str(tmp_path / "cache")
    code, out, _ = run("scrape", "books", "--url", url, "--pages", "2", "--delay", "0", "--cache-dir", cache,
                       "--db", db, "--out", out_dir, capsys=capsys)
    assert code == 0 and "Scraped 8 products" in out
    report = json.loads(out[out.index("{"):])
    assert report["extracted"] == 8 and report["loaded"] == 8
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM products").fetchone()[0] == 8

    # a second run is served from the page cache and adds a price-history row per product
    code, out, _ = run("scrape", "books", "--url", url, "--pages", "2", "--delay", "0", "--cache-dir", cache,
                       "--db", db, "--out", out_dir, capsys=capsys)
    assert code == 0 and "from cache" in out and "0 from cache" not in out
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 16

    code, out, _ = run("report", "--db", db, "--out", out_dir, capsys=capsys)
    assert code == 0 and (tmp_path / "o" / "report.md").read_text().startswith("# E-commerce insights report")


def test_dynamic_scraper_requires_a_url(capsys):
    code, _, err = run("scrape", "dynamic", capsys=capsys)
    assert code == 2 and "--url is required" in err


def test_dynamic_scraper_explains_a_missing_chrome(monkeypatch, capsys):
    def no_chrome(headless=True):
        raise RuntimeError("Unable to obtain driver for chrome\nlong selenium help text")
    monkeypatch.setattr(dynamic, "make_driver", no_chrome)
    code, out, err = run("scrape", "dynamic", "--url", "http://127.0.0.1:1", capsys=capsys)
    assert code == 1 and out == ""
    assert "Could not start Chrome" in err and "Install Google Chrome" in err and "Traceback" not in err


def test_dynamic_scraper_runs_the_pipeline_and_always_quits_the_browser(monkeypatch, tmp_path, capsys):
    from tests.test_dynamic_and_demo_shop import FakeBrowser
    from ecom_insights import demo_shop

    browser = FakeBrowser(demo_shop.build_catalogue())
    quits = []
    browser.quit = lambda: quits.append(True)
    monkeypatch.setattr(dynamic, "make_driver", lambda headless=True: browser)
    code, out, _ = run("scrape", "dynamic", "--url", "http://shop.test", "--db", str(tmp_path / "d.db"),
                       "--out", str(tmp_path / "o"), capsys=capsys)
    assert code == 0 and "Scraped 75 products" in out and '"loaded": 69' in out
    assert quits == [True]


def test_unknown_command_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["nonsense"])
    assert exc.value.code == 2
