"""Scraper for Anthropic Careers (Education roles only).

https://www.anthropic.com/careers/jobs is a server-rendered view of Anthropic's
Greenhouse job board: every "Apply" link on that page points straight at
job-boards.greenhouse.io, and the page embeds the same departments payload this
scraper reads. Reading the board API directly means no headless browser and no
CSS selectors to rot when the careers page is restyled.

Education roles live under the "Technical Education" department, which is what
the careers page groups them under. Greenhouse also gives us a real posting date
(`first_published`), so these jobs carry a `posted_date`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime

from .base import BaseScraper, Job

log = logging.getLogger(__name__)

# `render_as=list` returns every department with its jobs inlined in one request.
BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/anthropic/departments?render_as=list"

# The public page this board backs. Not fetched — kept for orientation.
CAREERS_URL = "https://www.anthropic.com/careers/jobs"

REQUEST_TIMEOUT = 30

USER_AGENT = "daily_job_scraper (+https://github.com/Victor-Palacios/daily_job_scraper)"

# Anthropic files these roles under "Technical Education". Matching the word
# rather than the exact string keeps a rename to plain "Education" working.
DEPARTMENT_RE = re.compile(r"\beducation\b", re.IGNORECASE)

# Fallback, used *only* when the board has no education department at all (the
# team was renamed or folded into another org). Without it a reorg would turn
# into the silent "0 jobs forever" failure the README warns about. It is
# deliberately not OR'd into the normal path: today it would also pull in
# education-adjacent Sales roles, which isn't what this scraper is for.
TITLE_FALLBACK_RE = re.compile(
    r"\b(education|educator|instructor|curriculum|technical training|technical trainer)\b",
    re.IGNORECASE,
)


class AnthropicScraper(BaseScraper):
    company = "Anthropic"

    async def fetch(self) -> list[Job]:
        log.info("Anthropic: loading %s", BOARD_URL)
        try:
            # urlopen is blocking; keep the scraper cooperative under asyncio.gather.
            payload = await asyncio.to_thread(_get_board)
        except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as e:
            log.warning("Anthropic: board request failed (%s); returning 0", e)
            return []

        jobs = jobs_from_departments(payload.get("departments") or [], company=self.company)
        log.info("Anthropic: parsed %d jobs", len(jobs))
        return jobs


def _get_board() -> dict:
    req = urllib.request.Request(
        BOARD_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def jobs_from_departments(departments: list[dict], company: str = "Anthropic") -> list[Job]:
    """Map the Greenhouse departments payload to education `Job`s, newest first."""
    matched = [d for d in departments if DEPARTMENT_RE.search(d.get("name") or "")]
    if matched:
        pairs = [(d.get("name") or "", j) for d in matched for j in (d.get("jobs") or [])]
    else:
        log.warning(
            "Anthropic: no education department on the board; "
            "falling back to a title keyword match"
        )
        pairs = [
            (d.get("name") or "", j)
            for d in departments
            for j in (d.get("jobs") or [])
            if TITLE_FALLBACK_RE.search(j.get("title") or "")
        ]

    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for dept_name, raw in pairs:
        job_id = str(raw.get("id") or "").strip()
        title = (raw.get("title") or "").strip()
        url = (raw.get("absolute_url") or "").strip()
        # A job can be listed under more than one department; keep the first.
        if not job_id or not title or not url or job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        jobs.append(Job(
            company=company,
            job_id=job_id,
            title=title,
            location=((raw.get("location") or {}).get("name") or "").strip(),
            url=url,
            posted_date=_parse_published(raw.get("first_published")),
            team=dept_name or None,
        ))

    jobs.sort(key=lambda j: (j.posted_date or date.min, j.title), reverse=True)
    return jobs


def _parse_published(value: str | None) -> date | None:
    """Parse Greenhouse's ISO-8601 `first_published` (e.g. '2026-09-04T12:11:40-04:00')."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None
