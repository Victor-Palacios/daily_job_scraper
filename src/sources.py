"""The list of job boards this scraper watches.

Adding a company is one line, as long as it runs Greenhouse, Ashby or Workday.
Find the token in the company's careers URL or its "Apply" links, and confirm
it resolves before adding it:

    https://boards-api.greenhouse.io/v1/boards/<token>/departments?render_as=list
    https://api.ashbyhq.com/posting-api/job-board/<token>
    POST https://<host>/wday/cxs/<tenant>/<site>/jobs   {"limit":1,"offset":0,"searchText":""}

Matchers (src/scrapers/matchers.py):
  ANTHROPIC_EDUCATION  the whole board is Claude, so only "does it teach?"
  TEACHING_AT_AI_COMPANY  a teaching role at a company that IS an AI company;
                          no content test, because every posting there says AI
  AI_TEACHING          a teaching role proven to be about AI by its description;
                       for companies that teach many subjects
  CLAUDE_TEACHING      as above but Claude must be the subject; kept for any
                       board that turns out too noisy under AI_TEACHING
"""
from __future__ import annotations

from .scrapers.ashby import AshbyScraper
from .scrapers.base import BaseScraper
from .scrapers.greenhouse import GreenhouseScraper
from .scrapers.matchers import AI_TEACHING, ANTHROPIC_EDUCATION, TEACHING_AT_AI_COMPANY
from .scrapers.workday import WorkdayScraper

# Workday boards are too big to walk, so the search is pushed server-side.
# These terms mirror PARTNER_TEACHING_RE -- widen both together.
TEACHING_SEARCHES = (
    "instructor", "training", "enablement", "evangelist",
    "education", "curriculum", "advocate",
)


def build_scrapers() -> list[BaseScraper]:
    """Every active source, in digest order."""
    return [
        # --- Anthropic ------------------------------------------------------
        GreenhouseScraper("Anthropic", "anthropic", ANTHROPIC_EDUCATION),

        # --- Claude partner firms -------------------------------------------
        # NewRocket's board is branded "highmetric" after a company it merged
        # with; the token not matching the name is normal for Greenhouse.
        GreenhouseScraper("NewRocket", "highmetric", TEACHING_AT_AI_COMPANY),
        GreenhouseScraper("Caylent", "caylent", TEACHING_AT_AI_COMPANY),

        # --- Training vendors and courseware --------------------------------
        GreenhouseScraper("Correlation One", "correlationone", AI_TEACHING),
        GreenhouseScraper("DataCamp", "datacamp", AI_TEACHING),
        GreenhouseScraper("CodePath", "codepath", AI_TEACHING),
        GreenhouseScraper("General Assembly", "generalassembly", AI_TEACHING),

        # --- Claude-native developer tools ----------------------------------
        AshbyScraper("Cursor", "cursor", TEACHING_AT_AI_COMPANY),
        AshbyScraper("Replit", "replit", TEACHING_AT_AI_COMPANY),
        AshbyScraper("Cognition", "cognition", TEACHING_AT_AI_COMPANY),
        AshbyScraper("Factory", "factory", TEACHING_AT_AI_COMPANY),
        AshbyScraper("Notion", "notion", TEACHING_AT_AI_COMPANY),

        # --- AI-product enterprises (Workday) -------------------------------
        # Intapp sells "Celeste", its own agentic platform, and never names a
        # model vendor -- the case that motivated AI_TEACHING. Small board, so
        # it is walked in full rather than searched.
        WorkdayScraper("Intapp", "intapp.wd1.myworkdayjobs.com", "Intapp",
                       TEACHING_AT_AI_COMPANY, search_terms=("",)),

        # --- Large enterprise boards (Workday) ------------------------------
        # ~1500 and ~2000 reqs; searched by keyword, never walked.
        WorkdayScraper("Salesforce", "salesforce.wd12.myworkdayjobs.com",
                       "External_Career_Site", AI_TEACHING,
                       search_terms=TEACHING_SEARCHES),
        WorkdayScraper("Booz Allen", "bah.wd1.myworkdayjobs.com", "BAH_Jobs",
                       AI_TEACHING, search_terms=TEACHING_SEARCHES),
    ]
