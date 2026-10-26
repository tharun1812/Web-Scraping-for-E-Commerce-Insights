"""A polite HTTP client: identifies itself, obeys robots.txt, rate-limits, retries and can cache pages."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_USER_AGENT = "ecom-insights-bot/1.0 (educational project; respects robots.txt)"


class RobotsDisallowed(PermissionError):
    pass


class PoliteSession:
    def __init__(self, min_delay: float = 1.0, timeout: float = 15.0, user_agent: str = DEFAULT_USER_AGENT,
                 respect_robots: bool = True, cache_dir: str | Path | None = None, retries: int = 3):
        self.min_delay, self.timeout, self.respect_robots = min_delay, timeout, respect_robots
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        retry = Retry(total=retries, backoff_factor=0.8, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET", "HEAD"), respect_retry_after_header=True)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.user_agent = user_agent
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request = 0.0
        self.requests_made = 0
        self.cache_hits = 0

    # -- robots.txt -----------------------------------------------------------------------------
    def _robots_for(self, url: str) -> RobotFileParser | None:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = RobotFileParser()
            try:
                resp = self.session.get(f"{origin}/robots.txt", timeout=self.timeout)
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    self._robots[origin] = rp
                else:
                    self._robots[origin] = None     # no robots.txt: nothing is disallowed
            except requests.RequestException:
                self._robots[origin] = None
        return self._robots[origin]

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url) if self.respect_robots else None
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    # -- fetching -------------------------------------------------------------------------------
    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html")

    def get(self, url: str) -> str:
        """Return the page HTML. Raises RobotsDisallowed or requests.HTTPError on failure."""
        cached = self._cache_path(url)
        if cached and cached.exists():
            self.cache_hits += 1
            return cached.read_text(encoding="utf-8")
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows fetching {url}")

        wait = self.min_delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        resp = self.session.get(url, timeout=self.timeout)
        self._last_request = time.monotonic()
        self.requests_made += 1
        resp.raise_for_status()
        resp.encoding = "utf-8"      # many shop sites omit the charset; guessing latin-1 turns "£" into "Â£"
        html = resp.text
        if cached:
            cached.write_text(html, encoding="utf-8")
        return html
