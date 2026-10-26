"""Command line interface: python -m ecom_insights <scrape|demo|demo-site|report>."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .analysis.insights import build_report
from .etl.pipeline import run_pipeline
from .http import PoliteSession


def _print_report(report) -> None:
    print(json.dumps(report.to_dict(), indent=2))


def _cmd_scrape(args: argparse.Namespace) -> int:
    if args.site == "books":
        from .scrapers import books
        session = PoliteSession(min_delay=args.delay, cache_dir=args.cache_dir)
        raw = list(books.scrape(session, base_url=args.url or books.DEFAULT_BASE_URL, max_pages=args.pages,
                                details=not args.no_details))
        print(f"Scraped {len(raw)} products with {session.requests_made} requests ({session.cache_hits} from cache).")
        source = books.SOURCE
    else:
        from .scrapers import dynamic
        if not args.url:
            print("--url is required for the dynamic scraper (for example http://127.0.0.1:8000)", file=sys.stderr)
            return 2
        try:
            driver = dynamic.make_driver(headless=not args.headed)
        except Exception as exc:  # Chrome or its driver is missing, blocked, or the wrong version
            print("Could not start Chrome for the dynamic scraper.\n"
                  "Install Google Chrome (https://www.google.com/chrome/), then try again. "
                  "Selenium downloads the matching driver automatically, so the machine also needs internet access.\n"
                  f"Details: {type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}", file=sys.stderr)
            return 1
        try:
            raw = list(dynamic.scrape(driver, args.url))
        finally:
            driver.quit()
        print(f"Scraped {len(raw)} products from the rendered page.")
        source = dynamic.SOURCE
    _print_report(run_pipeline(raw, args.db, args.out, source=source))
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from .demo_shop import catalogue_as_raw
    print("Running the ETL on the bundled demo catalogue (no network or browser needed)...")
    _print_report(run_pipeline(catalogue_as_raw(), args.db, args.out, source="demo_dynamic_shop"))
    print(f"Report: {build_report(args.db, args.out)}")
    return 0


def _cmd_demo_site(args: argparse.Namespace) -> int:
    from .demo_shop import create_demo_app
    print(f"Demo shop on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    create_demo_app().run(host="127.0.0.1", port=args.port)
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    print(f"Report: {build_report(args.db, args.out)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ecom_insights", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--db", default="data/shop.db")
        sp.add_argument("--out", default="data/output")

    s = sub.add_parser("scrape", help="scrape a site, then clean, validate and load the data")
    common(s)
    s.add_argument("site", choices=["books", "dynamic"])
    s.add_argument("--url", help="base URL (books: defaults to books.toscrape.com; dynamic: required)")
    s.add_argument("--pages", type=int, help="books: maximum listing pages (20 products each)")
    s.add_argument("--no-details", action="store_true", help="books: skip product pages (faster, fewer fields)")
    s.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    s.add_argument("--cache-dir", help="cache downloaded pages here to avoid re-requesting them")
    s.add_argument("--headed", action="store_true", help="dynamic: show the browser window")
    s.set_defaults(func=_cmd_scrape)

    d = sub.add_parser("demo", help="offline demo: ETL + report on the bundled messy catalogue")
    common(d)
    d.set_defaults(func=_cmd_demo)

    w = sub.add_parser("demo-site", help="serve the JavaScript demo shop for the Selenium scraper")
    w.add_argument("--port", type=int, default=8000)
    w.set_defaults(func=_cmd_demo_site)

    r = sub.add_parser("report", help="build the insights report from the database")
    common(r)
    r.set_defaults(func=_cmd_report)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
