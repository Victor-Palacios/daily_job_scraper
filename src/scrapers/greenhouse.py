"""Generic scraper for any public Greenhouse job board.

Greenhouse exposes every board at boards-api.greenhouse.io with no auth, which
is why the active sources are all boards rather than career pages: one request
for the listing, no headless browser, no CSS selectors to rot.

`?render_as=list` on the departments endpoint returns every department with its
jobs inlined, which is the only place the department name is available. The
listing carries no description, so a matcher that needs one costs a second
request per shortlisted job -- bounded by CONTENT_CONCURRENCY.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date, datetime

from .base import BaseScraper, Job, dedupe_jobs
from .http import FetchError, get_json
from .matchers import Matcher, looks_like_boilerplate

log = logging.getLogger(__name__)

DEPARTMENTS_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/departments?render_as=list"
JOB_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"

# Politeness cap on the per-job description fetches for one board.
CONTENT_CONCURRENCY = 5

# How many already-rejected postings to read when checking a board for Claude
# boilerplate. Small: this is a per-run cost on every content-matching board,
# and the signal saturates quickly.
BASELINE_SAMPLE_SIZE = 6

_TAG_RE = re.compile(r"<[^>]+>")


class GreenhouseScraper(BaseScraper):
    def __init__(self, company: str, board_token: str, matcher: Matcher):
        self.company = company
        self.board_token = board_token
        self.matcher = matcher

    @property
    def source_id(self) -> str:
        return f"greenhouse:{self.board_token}"

    async def fetch(self) -> list[Job]:
        url = DEPARTMENTS_URL.format(token=self.board_token)
        try:
            payload = await asyncio.to_thread(get_json, url)
        except FetchError as e:
            log.warning("%s: board request failed (%s); returning 0", self.company, e)
            return []

        departments = payload.get("departments") or []
        shortlisted = []
        rejected = []
        for d in departments:
            dept_name = d.get("name") or ""
            for raw in (d.get("jobs") or []):
                if self.matcher.shortlist(raw.get("title") or "", dept_name):
                    shortlisted.append((dept_name, raw))
                else:
                    rejected.append(raw)

        content_trusted = True
        if self.matcher.needs_content:
            contents = await self._fetch_contents([raw for _, raw in shortlisted])
            # Sample postings the matcher already rejected: any Claude mention in
            # those is template text, not the job. If most of them mention Claude,
            # descriptions carry no signal on this board.
            sample = await self._fetch_contents(_baseline_sample(rejected))
            if looks_like_boilerplate(sample):
                content_trusted = False
                log.info(
                    "%s: board mentions Claude in unrelated postings; "
                    "requiring it in the title or department instead",
                    self.company,
                )
        else:
            contents = ["" for _ in shortlisted]

        jobs: list[Job] = []
        for (dept_name, raw), content in zip(shortlisted, contents):
            title = (raw.get("title") or "").strip()
            if not self.matcher.confirm(title, dept_name, content, content_trusted):
                continue
            job_id = str(raw.get("id") or "").strip()
            url = (raw.get("absolute_url") or "").strip()
            if not job_id or not title or not url:
                continue
            jobs.append(Job(
                company=self.company,
                job_id=job_id,
                title=title,
                location=((raw.get("location") or {}).get("name") or "").strip(),
                url=url,
                posted_date=parse_published(raw.get("first_published")),
                team=dept_name or None,
            ))

        jobs = dedupe_jobs(jobs)
        jobs.sort(key=lambda j: (j.posted_date or date.min, j.title), reverse=True)
        log.info(
            "%s: %d shortlisted -> %d matched (%s)",
            self.company, len(shortlisted), len(jobs), self.matcher.name,
        )
        if departments and not jobs:
            log.info("%s: board has %d departments but nothing matched", self.company, len(departments))
        return jobs

    async def _fetch_contents(self, raws: list[dict]) -> list[str]:
        """Fetch each shortlisted job's description; failures become empty strings."""
        sem = asyncio.Semaphore(CONTENT_CONCURRENCY)

        async def one(raw: dict) -> str:
            job_id = str(raw.get("id") or "").strip()
            if not job_id:
                return ""
            url = JOB_URL.format(token=self.board_token, job_id=job_id)
            async with sem:
                try:
                    detail = await asyncio.to_thread(get_json, url)
                except FetchError as e:
                    # One unreadable description shouldn't sink the whole board.
                    log.warning("%s: could not read job %s (%s)", self.company, job_id, e)
                    return ""
            return strip_html(detail.get("content") or "")

        return await asyncio.gather(*(one(r) for r in raws))


def _baseline_sample(rejected: list[dict]) -> list[dict]:
    """Pick a stable spread of rejected postings to test for Claude boilerplate.

    Sorted by id and evenly spaced rather than taking the first N, so the sample
    isn't all from whichever department happens to sort first, and so it stays
    the same between runs.
    """
    ordered = sorted(rejected, key=lambda r: str(r.get("id") or ""))
    if len(ordered) <= BASELINE_SAMPLE_SIZE:
        return ordered
    step = len(ordered) / BASELINE_SAMPLE_SIZE
    return [ordered[int(i * step)] for i in range(BASELINE_SAMPLE_SIZE)]


def strip_html(raw: str) -> str:
    """Greenhouse returns HTML-escaped markup; flatten it to searchable text."""
    return _TAG_RE.sub(" ", html.unescape(raw))


def parse_published(value: str | None) -> date | None:
    """Parse an ISO-8601 timestamp (e.g. '2026-09-04T12:11:40-04:00')."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, TypeError, AttributeError):
        return None
