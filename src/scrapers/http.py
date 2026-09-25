"""Tiny JSON-over-HTTPS helper shared by the board scrapers.

Deliberately stdlib-only: every active source is a public JSON job-board API,
so there is nothing here worth taking a dependency for.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
USER_AGENT = "daily_job_scraper (+https://github.com/Victor-Palacios/daily_job_scraper)"


class FetchError(RuntimeError):
    """A board request failed. Callers log it and fall back to zero jobs."""


def get_json(url: str) -> dict:
    """GET `url` and parse JSON, raising FetchError for any network/parse failure."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
        raise FetchError(f"{url}: {e}") from e
