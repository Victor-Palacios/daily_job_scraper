"""The list of job boards this scraper watches.

Adding a company is one line here, as long as it runs Greenhouse or Ashby.
Find the board token in the company's careers-page URL (or its "Apply" links)
and confirm it resolves before adding it:

    https://boards-api.greenhouse.io/v1/boards/<token>/departments?render_as=list
    https://api.ashbyhq.com/posting-api/job-board/<token>

Boards on Workday, SmartRecruiters, or a bespoke SPA are deliberately absent:
they have no public JSON and would drag Playwright and CSS selectors back into
a pipeline that currently has neither. AWS, Salesforce, Booz Allen and
Capgemini all fall in that bucket.
"""
from __future__ import annotations

from .scrapers.ashby import AshbyScraper
from .scrapers.base import BaseScraper
from .scrapers.greenhouse import GreenhouseScraper
from .scrapers.matchers import ANTHROPIC_EDUCATION, CLAUDE_TEACHING


def build_scrapers() -> list[BaseScraper]:
    """Every active source, in digest order."""
    return [
        # --- Anthropic ------------------------------------------------------
        # The whole board is Claude, so the only question is whether a role
        # teaches. Matched on the Technical Education department plus teaching
        # titles elsewhere.
        GreenhouseScraper("Anthropic", "anthropic", ANTHROPIC_EDUCATION),

        # --- Claude partner firms -------------------------------------------
        # Consultancies with a dedicated Anthropic practice. NewRocket's board
        # is branded "highmetric" after a company it merged with -- the token
        # does not match the name, which is normal for Greenhouse.
        GreenhouseScraper("NewRocket", "highmetric", CLAUDE_TEACHING),
        GreenhouseScraper("Caylent", "caylent", CLAUDE_TEACHING),

        # --- Training vendors and courseware --------------------------------
        GreenhouseScraper("Correlation One", "correlationone", CLAUDE_TEACHING),
        GreenhouseScraper("DataCamp", "datacamp", CLAUDE_TEACHING),
        GreenhouseScraper("CodePath", "codepath", CLAUDE_TEACHING),
        GreenhouseScraper("General Assembly", "generalassembly", CLAUDE_TEACHING),

        # --- Claude-native developer tools ----------------------------------
        # Products built on Claude, where teaching the user is teaching Claude.
        AshbyScraper("Cursor", "cursor", CLAUDE_TEACHING),
        AshbyScraper("Replit", "replit", CLAUDE_TEACHING),
        AshbyScraper("Cognition", "cognition", CLAUDE_TEACHING),
        AshbyScraper("Factory", "factory", CLAUDE_TEACHING),
        AshbyScraper("Notion", "notion", CLAUDE_TEACHING),
    ]
