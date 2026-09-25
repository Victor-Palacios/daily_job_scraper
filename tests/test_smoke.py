"""Smoke tests — verify modules import and pure functions work."""
from datetime import date
from pathlib import Path

from src.scrapers.apple import _parse_posted as apple_parse
from src.scrapers.ashby import jobs_from_postings
from src.scrapers.base import Job, dedupe_jobs
from src.scrapers.greenhouse import _baseline_sample, parse_published, strip_html
from src.scrapers.matchers import (
    ANTHROPIC_EDUCATION,
    CLAUDE_TEACHING,
    looks_like_boilerplate,
)
from src.seen_store import SeenStore


def job(company="Anthropic", job_id="1", title="t", location="", posted=None):
    return Job(
        company=company, job_id=job_id, title=title, location=location,
        url=f"https://example.com/{job_id}", posted_date=posted,
    )


# --- date / html helpers ----------------------------------------------------

def test_apple_parse_posted():
    assert apple_parse("Posted: Apr 15, 2026") == date(2026, 4, 15)
    assert apple_parse("Apr 15, 2026") == date(2026, 4, 15)
    assert apple_parse("") is None
    assert apple_parse("nonsense") is None


def test_parse_published_handles_offsets_and_z():
    assert parse_published("2026-09-04T12:11:40-04:00") == date(2026, 9, 4)
    assert parse_published("2026-09-04T12:11:40Z") == date(2026, 9, 4)
    assert parse_published(None) is None
    assert parse_published("") is None
    assert parse_published("nonsense") is None


def test_strip_html_unescapes_and_flattens():
    out = strip_html("&lt;p&gt;Teach &lt;b&gt;Claude&lt;/b&gt; well&lt;/p&gt;")
    assert "Claude" in out
    assert "<" not in out and "&lt;" not in out


# --- dedup ------------------------------------------------------------------

def test_dedupe_drops_repeated_ids():
    j = job(job_id="7", title="Instructor")
    assert len(dedupe_jobs([j, j])) == 1


def test_dedupe_collapses_reposts_keeping_earliest():
    """DataCamp posts one req four times under different ids."""
    jobs = [
        job(job_id="7966303", title="Curriculum Manager - Cloud", location="UK", posted=date(2026, 5, 29)),
        job(job_id="7966314", title="Curriculum Manager - Cloud", location="UK", posted=date(2026, 6, 1)),
        job(job_id="7966315", title="Curriculum Manager - Cloud", location="UK", posted=date(2026, 6, 2)),
    ]
    out = dedupe_jobs(jobs)
    assert len(out) == 1
    assert out[0].job_id == "7966303"


def test_dedupe_keeps_reqs_that_differ_by_location():
    """NewRocket's East and West territories are genuinely separate jobs."""
    jobs = [
        job(job_id="a", title="Technology Trainer", location="Remote Eastern US"),
        job(job_id="b", title="Technology Trainer", location="Remote Western US"),
    ]
    assert len(dedupe_jobs(jobs)) == 2


# --- Anthropic matcher (behaviour preserved from the original scraper) ------

def test_anthropic_matches_education_department():
    assert ANTHROPIC_EDUCATION.shortlist("Technical Documentation Engineer", "Technical Education")


def test_anthropic_matches_teaching_titles_anywhere():
    for title in ("Lead Technical Instructor", "Head of Technical Training",
                  "Developer Education Lead, Claude Platform", "Curriculum Designer"):
        assert ANTHROPIC_EDUCATION.shortlist(title, "Sales"), title


def test_anthropic_excludes_ml_training_roles():
    for title in ("Research Scientist, Pre-training", "Research Engineer, Model Post-Training",
                  "Pre-training Data Infrastructure Engineer", "Training Infrastructure Engineer"):
        assert not ANTHROPIC_EDUCATION.shortlist(title, "AI Research & Engineering"), title


def test_anthropic_department_beats_ml_training_exclusion():
    assert ANTHROPIC_EDUCATION.shortlist("Engineer, Training Data Curation", "Technical Education")


# --- Claude-teaching matcher ------------------------------------------------

def test_claude_teaching_needs_a_teaching_signal():
    assert CLAUDE_TEACHING.shortlist("Technology Trainer – Anthropic Enablement", "Delivery")
    assert CLAUDE_TEACHING.shortlist("Lead Instructor: AI Augmented Engineering", "Programs")
    assert not CLAUDE_TEACHING.shortlist("Staff Software Engineer", "Engineering")
    assert not CLAUDE_TEACHING.shortlist("Account Executive", "Sales")


def test_claude_teaching_confirms_on_title_without_reading_content():
    assert CLAUDE_TEACHING.confirm("Technology Trainer – Anthropic Enablement", "Delivery", "")


def test_claude_teaching_needs_two_content_mentions():
    """One mention is usually a company blurb; the curriculum names it twice."""
    assert not CLAUDE_TEACHING.confirm("Lead Instructor", "Programs", "We partner with Anthropic.")
    assert CLAUDE_TEACHING.confirm(
        "Lead Instructor", "Programs",
        "Curriculum covers Claude Code and agentic workflows. Strong Claude experience required.",
    )


def test_claude_teaching_ignores_content_when_board_is_boilerplate():
    """Caylent names Claude in every posting, so descriptions stop being evidence."""
    content = "A charter member of Anthropic's Claude Partner Network. We combine Claude expertise."
    assert CLAUDE_TEACHING.confirm("Principal Data Architect — Databricks Enablement", "Data", content)
    assert not CLAUDE_TEACHING.confirm(
        "Principal Data Architect — Databricks Enablement", "Data", content, content_trusted=False
    )
    # A title hit still wins on a boilerplate board.
    assert CLAUDE_TEACHING.confirm("Claude Trainer", "Data", content, content_trusted=False)


def test_looks_like_boilerplate():
    blurb = "We are a charter member of Anthropic's Claude Partner Network."
    assert looks_like_boilerplate([blurb] * 6)
    assert not looks_like_boilerplate(["Build data pipelines."] * 6)
    # Too small a sample to conclude anything.
    assert not looks_like_boilerplate([blurb, blurb])


def test_baseline_sample_is_bounded_and_stable():
    rejected = [{"id": i} for i in range(100)]
    first = _baseline_sample(rejected)
    assert len(first) == 6
    assert first == _baseline_sample(rejected)
    assert _baseline_sample([{"id": 1}]) == [{"id": 1}]


# --- Ashby end-to-end mapping ----------------------------------------------

ASHBY_BOARD = [
    {
        "id": "abc", "title": "Product Education Engineer", "department": "Growth",
        "location": "San Francisco", "jobUrl": "https://jobs.ashbyhq.com/x/abc",
        "publishedAt": "2026-09-01T00:00:00Z",
        "descriptionPlain": "Teach users to build with Claude. Claude Code expertise required.",
    },
    {
        "id": "def", "title": "Staff Backend Engineer", "department": "Infra",
        "location": "Remote", "jobUrl": "https://jobs.ashbyhq.com/x/def",
        "publishedAt": "2026-09-02T00:00:00Z", "descriptionPlain": "Scale our Claude-backed API.",
    },
    {
        "id": "ghi", "title": "Curriculum Lead", "department": "Education",
        "location": "NYC", "jobUrl": "https://jobs.ashbyhq.com/x/ghi",
        "publishedAt": "2026-09-03T00:00:00Z", "descriptionPlain": "Own our GPT-4 course catalog.",
        "isListed": False,
    },
]


def test_ashby_keeps_only_claude_teaching_roles():
    jobs = jobs_from_postings(ASHBY_BOARD, company="Cursor", matcher=CLAUDE_TEACHING)
    assert [j.title for j in jobs] == ["Product Education Engineer"]
    j = jobs[0]
    assert j.company == "Cursor"
    assert j.job_id == "abc"
    assert j.location == "San Francisco"
    assert j.posted_date == date(2026, 9, 1)
    assert j.team == "Growth"
    assert j.dedup_key == "Cursor::abc"


def test_ashby_skips_unlisted_postings():
    """The unlisted Curriculum Lead must not appear even if it matched."""
    assert all(j.job_id != "ghi" for j in jobs_from_postings(
        ASHBY_BOARD, company="Cursor", matcher=CLAUDE_TEACHING))


# --- seen store -------------------------------------------------------------

def test_seen_store_filters_duplicates(tmp_path: Path):
    store = SeenStore(path=tmp_path / "seen.json")
    jobs = [
        Job(company="Apple", job_id="A1", title="ML Engineer", location="Cupertino", url="https://apple.com/a1"),
        Job(company="Google", job_id="G1", title="Data Scientist", location="MTV", url="https://google.com/g1"),
    ]
    first = store.filter_new(jobs)
    assert len(first) == 2
    # Second pass with the same jobs yields nothing.
    second = store.filter_new(jobs)
    assert second == []
    # Adding a new job surfaces only it.
    jobs.append(Job(company="Apple", job_id="A2", title="Research Scientist", location="Austin", url="https://apple.com/a2"))
    third = store.filter_new(jobs)
    assert len(third) == 1 and third[0].job_id == "A2"


def test_seen_store_persists(tmp_path: Path):
    path = tmp_path / "seen.json"
    s1 = SeenStore(path=path)
    s1.filter_new([Job(company="Apple", job_id="X", title="t", location="", url="u")])
    s1.save()

    s2 = SeenStore(path=path)
    again = s2.filter_new([Job(company="Apple", job_id="X", title="t", location="", url="u")])
    assert again == []
