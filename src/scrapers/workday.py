"""Generic scraper for a public Workday board.

Workday career sites look like JavaScript SPAs, but every one is backed by an
unauthenticated JSON API ("CXS") that the page itself calls:

    POST https://{host}/wday/cxs/{tenant}/{site}/jobs     -- paged listing
    GET  https://{host}/wday/cxs/{tenant}/{site}{path}    -- one posting

So Workday needs no browser either. The listing carries no description and
only a relative "Posted 23 Days Ago" date, so anything interesting requires a
detail fetch -- which also yields `startDate` and the salary text.

Boards here are far bigger than Greenhouse ones (Booz Allen lists ~2000 reqs),
so `search_terms` pushes the filtering server-side: query for the words that
could plausibly match instead of walking the whole board. MAX_DETAIL_FETCHES
then caps what one board can cost in a single run.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date

from .base import BaseScraper, Job, dedupe_jobs
from .greenhouse import parse_published, strip_html
from .http import FetchError, get_json, post_json
from .matchers import Matcher, looks_like_boilerplate

log = logging.getLogger(__name__)

PAGE_SIZE = 20          # Workday rejects larger pages.
MAX_PAGES = 5           # Per search term.
MAX_DETAIL_FETCHES = 40  # Per board, per run.
DETAIL_CONCURRENCY = 4

# Req id out of an externalPath like /job/Palo-Alto-CA/Some-Title_R2025346-1
_REQ_RE = re.compile(r"_([A-Za-z0-9-]+)$")


class WorkdayScraper(BaseScraper):
    def __init__(
        self,
        company: str,
        host: str,
        site: str,
        matcher: Matcher,
        search_terms: tuple[str, ...] = ("",),
        tenant: str | None = None,
    ):
        self.company = company
        self.host = host
        self.site = site
        self.matcher = matcher
        self.search_terms = search_terms
        # The CXS path repeats the tenant, which is the first label of the host
        # (intapp.wd1.myworkdayjobs.com -> intapp).
        self.tenant = tenant or host.split(".")[0]

    @property
    def source_id(self) -> str:
        return f"workday:{self.host}/{self.site}"

    @property
    def _base(self) -> str:
        return f"https://{self.host}/wday/cxs/{self.tenant}/{self.site}"

    async def fetch(self) -> list[Job]:
        try:
            postings = await self._list_postings()
        except FetchError as e:
            log.warning("%s: board request failed (%s); returning 0", self.company, e)
            return []

        shortlisted, rejected = [], []
        for raw in postings:
            title = (raw.get("title") or "").strip()
            if self.matcher.shortlist(title, ""):
                shortlisted.append(raw)
            else:
                rejected.append(raw)

        if len(shortlisted) > MAX_DETAIL_FETCHES:
            log.warning(
                "%s: %d shortlisted exceeds the %d detail-fetch cap; dropping the rest",
                self.company, len(shortlisted), MAX_DETAIL_FETCHES,
            )
            shortlisted = shortlisted[:MAX_DETAIL_FETCHES]

        details = await self._fetch_details(shortlisted)

        content_trusted = True
        if self.matcher.needs_content:
            sample = await self._fetch_details(rejected[:6])
            if looks_like_boilerplate(
                [d.get("text", "") for d in sample if d], self.matcher.subject_re
            ):
                content_trusted = False
                log.info(
                    "%s: board mentions the subject in unrelated postings; "
                    "requiring it in the title instead", self.company,
                )

        jobs: list[Job] = []
        for raw, detail in zip(shortlisted, details):
            if not detail:
                continue
            title = (raw.get("title") or "").strip()
            if not self.matcher.confirm(title, "", detail.get("text", ""), content_trusted):
                continue
            path = raw.get("externalPath") or ""
            m = _REQ_RE.search(path)
            job_id = m.group(1) if m else path
            url = detail.get("url") or f"https://{self.host}/{self.site}{path}"
            if not job_id or not title or not url:
                continue
            jobs.append(Job(
                company=self.company,
                job_id=job_id,
                title=title,
                location=(detail.get("location") or raw.get("locationsText") or "").strip(),
                url=url,
                posted_date=parse_published(detail.get("start_date")),
                team=None,
                salary_text=detail.get("text", "")[:4000],
            ))

        jobs = dedupe_jobs(jobs)
        jobs.sort(key=lambda j: (j.posted_date or date.min, j.title), reverse=True)
        log.info(
            "%s: %d listed -> %d shortlisted -> %d matched (%s)",
            self.company, len(postings), len(shortlisted), len(jobs), self.matcher.name,
        )
        return jobs

    async def _list_postings(self) -> list[dict]:
        """Walk the paged listing for each search term, de-duplicated by path."""
        seen: dict[str, dict] = {}
        for term in self.search_terms:
            for page in range(MAX_PAGES):
                payload = {
                    "appliedFacets": {},
                    "limit": PAGE_SIZE,
                    "offset": page * PAGE_SIZE,
                    "searchText": term,
                }
                data = await asyncio.to_thread(post_json, f"{self._base}/jobs", payload)
                batch = data.get("jobPostings") or []
                for raw in batch:
                    path = raw.get("externalPath")
                    if path:
                        seen.setdefault(path, raw)
                total = data.get("total") or 0
                if len(batch) < PAGE_SIZE or (page + 1) * PAGE_SIZE >= total:
                    break
        return list(seen.values())

    async def _fetch_details(self, raws: list[dict]) -> list[dict | None]:
        sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def one(raw: dict) -> dict | None:
            path = raw.get("externalPath")
            if not path:
                return None
            async with sem:
                try:
                    data = await asyncio.to_thread(get_json, f"{self._base}{path}")
                except FetchError as e:
                    log.warning("%s: could not read %s (%s)", self.company, path, e)
                    return None
            info = data.get("jobPostingInfo") or {}
            return {
                "text": strip_html(html.unescape(info.get("jobDescription") or "")),
                "location": info.get("location") or "",
                "start_date": info.get("startDate"),
                "url": info.get("externalUrl") or "",
            }

        return await asyncio.gather(*(one(r) for r in raws))
