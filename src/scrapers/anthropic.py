"""Scraper for Anthropic Careers (Education roles only).

https://www.anthropic.com/careers/jobs is a server-rendered view of Anthropic's
Greenhouse job board: every "Apply" link on that page points straight at
job-boards.greenhouse.io, and the page embeds the same departments payload this
scraper reads. Reading the board API directly means no headless browser and no
CSS selectors to rot when the careers page is restyled.

A job is kept if *either* its department looks like education (today "Technical
Education", the grouping the careers page shows) *or* its title mentions
education / instruction / training. Both run on every pass, so a teaching role
filed under some other org still gets picked up.

Greenhouse also gives us a real posting date (`first_published`), so these jobs
carry a `posted_date`.
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
# rather than the exact string keeps a rename to plain "Education" working, and
# catches a future "Education Labs" or plain "Education" department too.
DEPARTMENT_RE = re.compile(r"\beducation\b", re.IGNORECASE)

# Title match, applied on every run alongside DEPARTMENT_RE (union, not a
# fallback) so a teaching role filed under Sales, People, or anywhere else is
# still caught.
TITLE_RE = re.compile(
    r"\b(education|educational|educator|instructor|instruction|instructional|"
    r"teaching|teacher|trainer|training|curriculum|pedagog\w*|upskilling)\b",
    re.IGNORECASE,
)

# "Training" is overloaded at an AI lab: without this, TITLE_RE's "training"
# pulls in every pre-training / post-training research and infra role on the
# board (5 of them as of this writing). These senses are never teaching roles,
# so they're subtracted from the title match. A department hit still wins --
# only TITLE_RE is filtered, so a genuinely education-department role named
# "...Training Data..." would survive.
ML_TRAINING_RE = re.compile(
    r"\b(pre|post)[\s-]?training\b|\bpretraining\b|\bposttraining\b|"
    r"\bmodel training\b|\btraining (data|infra\w*|cluster|stack|runtime|platform|compute)\b",
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

        departments = payload.get("departments") or []
        jobs = jobs_from_departments(departments, company=self.company)
        log.info("Anthropic: parsed %d jobs", len(jobs))
        if departments and not jobs:
            # The board loaded but nothing matched -- a reorg or a rename, not an
            # empty board. Loud, because the README's failure mode is a scraper
            # that quietly returns 0 forever.
            log.warning(
                "Anthropic: board returned %d departments but no education roles matched; "
                "check DEPARTMENT_RE / TITLE_RE against %s",
                len(departments), CAREERS_URL,
            )
        return jobs


def _get_board() -> dict:
    req = urllib.request.Request(
        BOARD_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_education_role(department: str, title: str) -> bool:
    """True if the department looks like education, or the title reads like one."""
    if DEPARTMENT_RE.search(department or ""):
        return True
    return bool(TITLE_RE.search(title or "")) and not ML_TRAINING_RE.search(title or "")


def jobs_from_departments(departments: list[dict], company: str = "Anthropic") -> list[Job]:
    """Map the Greenhouse departments payload to education `Job`s, newest first."""
    pairs = [
        (d.get("name") or "", j)
        for d in departments
        for j in (d.get("jobs") or [])
        if is_education_role(d.get("name") or "", j.get("title") or "")
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
