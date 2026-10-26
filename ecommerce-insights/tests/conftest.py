"""A mock bookstore (same HTML structure as books.toscrape.com) served over real HTTP on localhost."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

RATINGS = ["One", "Two", "Three", "Four", "Five"]
PAGES, PER_PAGE = 3, 4


def book(i: int) -> dict:
    return {"i": i, "title": f"Book Number {i}", "price": f"£{10 + i * 1.5:.2f}", "rating": RATINGS[i % 5],
            "upc": f"upc{i:04d}", "category": ["Poetry", "Travel", "Fiction"][i % 3], "stock": 5 + i}


def listing_html(page: int) -> str:
    cards = ""
    for i in range((page - 1) * PER_PAGE, page * PER_PAGE):
        b = book(i)
        cards += f"""<li class="col-xs-6"><article class="product_pod">
<div class="image_container"><a href="book_{i}/index.html"><img src="../media/{i}.jpg" alt="x"></a></div>
<p class="star-rating {b['rating']}"><i class="icon-star"></i></p>
<h3><a href="book_{i}/index.html" title="{b['title']}">{b['title'][:12]}...</a></h3>
<div class="product_price"><p class="price_color">{b['price']}</p>
<p class="instock availability"><i class="icon-ok"></i> In stock </p></div></article></li>"""
    nxt = f'<li class="next"><a href="page-{page + 1}.html">next</a></li>' if page < PAGES else ""
    return f'<html><head><meta charset="utf-8"></head><body><ol class="row">{cards}</ol><ul class="pager">{nxt}</ul></body></html>'


def detail_html(i: int) -> str:
    b = book(i)
    return f"""<html><head><meta charset="utf-8"></head><body>
<ul class="breadcrumb"><li><a href="/">Home</a></li><li><a href="/books">Books</a></li><li><a href="/c">{b['category']}</a></li><li class="active">{b['title']}</li></ul>
<div id="product_description" class="sub-header"><h2>Product Description</h2></div><p>A story about number {i}.</p>
<table class="table table-striped">
<tr><th>UPC</th><td>{b['upc']}</td></tr><tr><th>Product Type</th><td>Books</td></tr>
<tr><th>Price (excl. tax)</th><td>{b['price']}</td></tr><tr><th>Price (incl. tax)</th><td>{b['price']}</td></tr>
<tr><th>Availability</th><td>In stock ({b['stock']} available)</td></tr><tr><th>Number of reviews</th><td>{i % 4}</td></tr></table></body></html>"""


class Handler(BaseHTTPRequestHandler):
    hits: list[str] = []

    def log_message(self, *args):
        pass

    def _send(self, status: int, body: str, ctype: str = "text/html"):
        data = body.encode("utf-8")          # deliberately no charset in the header
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path
        Handler.hits.append(path)
        if path == "/robots.txt":
            return self._send(200, "User-agent: *\nDisallow: /private/\n", "text/plain")
        if path == "/private/secret.html":
            return self._send(200, "<html>secret</html>")
        if path in ("/", "/index.html"):
            return self._send(200, listing_html(1))
        if path.startswith("/page-"):
            return self._send(200, listing_html(int(path[6:-5])))
        if path.startswith("/book_"):
            i = int(path.split("_")[1].split("/")[0])
            if i == 5:
                return self._send(500, "boom")          # one broken product page
            return self._send(200, detail_html(i))
        self._send(404, "not found")


@pytest.fixture()
def mock_shop():
    Handler.hits = []
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/", Handler
    server.shutdown()
