"""Shared types and base class for company scrapers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from .salary import Salary, parse_salary


@dataclass(frozen=True)
class Job:
    company: str
    job_id: str          # Stable per-company identifier for dedup (from URL).
    title: str
    location: str
    url: str
    posted_date: date | None = None   # Apple has this; Google doesn't.
    team: str | None = None
    # Description text to mine for pay. Carried rather than parsed at scrape
    # time so the salary rules can change without re-scraping. Compared by
    # identity only -- it is bulky and never part of what makes a job unique.
    salary_text: str = field(default="", repr=False, compare=False)

    @property
    def dedup_key(self) -> str:
        return f"{self.company}::{self.job_id}"

    @property
    def salary(self) -> Salary | None:
        """Annual range if the posting states one, else None (= unknown)."""
        return parse_salary(self.salary_text)


def dedupe_jobs(jobs: list[Job]) -> list[Job]:
    """Drop repeat listings of one role, keeping the earliest.

    Two things cause duplicates. A job can sit in several departments, giving
    the same id twice. Worse, some boards post one role repeatedly under
    different ids -- DataCamp lists the same Curriculum Manager req four times,
    published within two minutes of each other -- which the seen-store cannot
    collapse because each id looks new. Same company, title and location is
    treated as the same job; keeping the earliest posting means a repost does
    not read as a new opening.

    Reqs that differ by location (NewRocket's East and West territories) are
    genuinely separate and survive.
    """
    best: dict[tuple[str, str], Job] = {}
    seen_ids: set[str] = set()
    for job in jobs:
        if job.job_id in seen_ids:
            continue
        seen_ids.add(job.job_id)
        key = (job.title.strip().lower(), job.location.strip().lower())
        current = best.get(key)
        if current is None:
            best[key] = job
        elif (job.posted_date or date.max) < (current.posted_date or date.max):
            best[key] = job
    return list(best.values())


class BaseScraper(ABC):
    """Each company scraper returns a list of Job objects for recent postings."""

    company: str

    @abstractmethod
    async def fetch(self) -> list[Job]:
        """Scrape and return the jobs currently listed on the first page of results."""
        raise NotImplementedError
