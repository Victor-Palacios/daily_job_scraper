"""Entry point: scrape each source, dedup against seen-store, and email a digest."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import load
from .emailer import send_job_digest
from .scrapers.base import BaseScraper, Job
from .seen_store import SeenStore
from .sources import build_scrapers

log = logging.getLogger("djs")

# Active sources live in src/sources.py -- add a company there, not here.
# Apple and Google are deactivated: their scrapers still sit in
# src/scrapers/apple.py and src/scrapers/google.py, so re-enabling either is an
# import plus a list entry (they also need the Playwright browser install that
# .github/workflows/scrape.yml no longer runs).
SCRAPERS: list[BaseScraper] = build_scrapers()


async def _scrape_one(scraper: BaseScraper) -> list[Job]:
    try:
        return await scraper.fetch()
    except Exception:
        log.exception("%s scraper failed", scraper.company)
        return []


async def run(dry_run: bool = False, reset_store: bool = False) -> int:
    results = await asyncio.gather(*(_scrape_one(s) for s in SCRAPERS))
    all_jobs: list[Job] = [j for sub in results for j in sub]
    log.info("Scraped %d jobs total", len(all_jobs))

    store = SeenStore()
    if reset_store:
        log.warning("Resetting seen-store \u2014 every job will be treated as new.")
        store._seen.clear()  # noqa: SLF001 \u2014 intentional for --reset-store

    new_jobs = store.filter_new(all_jobs)
    log.info("New (unseen) jobs: %d", len(new_jobs))
    for j in new_jobs:
        log.info("  [%s] %s \u2014 %s (%s)", j.company, j.title, j.location, j.posted_date or "?")

    if dry_run:
        log.info("Dry-run: skipping email send and not persisting seen-store.")
        return len(new_jobs)

    cfg = load()
    send_job_digest(new_jobs, cfg)
    store.save()
    return len(new_jobs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily job scraper \u2014 Claude teaching roles")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scrape and log results without sending email or persisting the seen-store.",
    )
    parser.add_argument(
        "--reset-store", action="store_true",
        help="Treat every scraped job as new (for first run / testing).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug-level logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    count = asyncio.run(run(dry_run=args.dry_run, reset_store=args.reset_store))
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
