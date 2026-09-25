"""Generic scraper for any public Ashby job board.

Ashby's posting API is the cheapest source here: one unauthenticated request
returns every listed job *with* `descriptionPlain`, so a content-matching
matcher costs nothing extra (unlike Greenhouse, which needs a second request
per job).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from .base import BaseScraper, Job, dedupe_jobs
from .greenhouse import parse_published
from .http import FetchError, get_json
from .matchers import Matcher, looks_like_boilerplate

log = logging.getLogger(__name__)

BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"


class AshbyScraper(BaseScraper):
    def __init__(self, company: str, board_token: str, matcher: Matcher):
        self.company = company
        self.board_token = board_token
        self.matcher = matcher

    @property
    def source_id(self) -> str:
        return f"ashby:{self.board_token}"

    async def fetch(self) -> list[Job]:
        url = BOARD_URL.format(token=self.board_token)
        try:
            payload = await asyncio.to_thread(get_json, url)
        except FetchError as e:
            log.warning("%s: board request failed (%s); returning 0", self.company, e)
            return []

        raws = payload.get("jobs") or []
        jobs = jobs_from_postings(raws, company=self.company, matcher=self.matcher)
        log.info(
            "%s: %d postings -> %d matched (%s)",
            self.company, len(raws), len(jobs), self.matcher.name,
        )
        return jobs


def jobs_from_postings(raws: list[dict], company: str, matcher: Matcher) -> list[Job]:
    """Map Ashby postings to `Job`s, newest first."""
    listed = [r for r in raws if r.get("isListed") is not False]

    # Ashby ships every description in the listing, so the Claude-boilerplate
    # baseline is free here -- no extra requests, unlike Greenhouse.
    content_trusted = True
    if matcher.needs_content:
        rejected = [
            r.get("descriptionPlain") or ""
            for r in listed
            if not matcher.shortlist(
                (r.get("title") or "").strip(),
                (r.get("department") or r.get("team") or "").strip(),
            )
        ]
        if looks_like_boilerplate(rejected):
            content_trusted = False
            log.info(
                "%s: board mentions Claude in unrelated postings; "
                "requiring it in the title or department instead",
                company,
            )

    jobs: list[Job] = []
    for raw in listed:
        title = (raw.get("title") or "").strip()
        department = (raw.get("department") or raw.get("team") or "").strip()
        if not matcher.shortlist(title, department):
            continue
        content = raw.get("descriptionPlain") or ""
        if not matcher.confirm(title, department, content, content_trusted):
            continue
        job_id = str(raw.get("id") or "").strip()
        url = (raw.get("jobUrl") or raw.get("applyUrl") or "").strip()
        if not job_id or not title or not url:
            continue
        jobs.append(Job(
            company=company,
            job_id=job_id,
            title=title,
            location=(raw.get("location") or "").strip(),
            url=url,
            posted_date=parse_published(raw.get("publishedAt")),
            team=department or None,
        ))

    jobs = dedupe_jobs(jobs)
    jobs.sort(key=lambda j: (j.posted_date or date.min, j.title), reverse=True)
    return jobs
