"""Smoke tests \u2014 verify modules import and pure functions work."""
from datetime import date
from pathlib import Path

from src.scrapers.anthropic import _parse_published as anthropic_parse
from src.scrapers.anthropic import is_education_role, jobs_from_departments
from src.scrapers.apple import _parse_posted as apple_parse
from src.scrapers.base import Job
from src.seen_store import SeenStore


def _dept(name: str, *jobs: dict) -> dict:
    return {"id": 1, "name": name, "parent_id": None, "jobs": list(jobs)}


def _raw_job(job_id: int, title: str, location: str, published: str | None) -> dict:
    """A trimmed copy of a real Greenhouse board entry."""
    return {
        "id": job_id,
        "title": title,
        "location": {"name": location},
        "absolute_url": f"https://job-boards.greenhouse.io/anthropic/jobs/{job_id}",
        "first_published": published,
    }


# Mirrors the live board: education roles sit in "Technical Education", other
# departments carry real teaching roles that MUST be picked up by title, and
# AI Research carries pre/post-training roles that must NOT be.
BOARD = [
    _dept(
        "Sales",
        _raw_job(1, "Developer Education Lead, Claude Platform", "Seattle, WA", "2026-09-18T15:41:44-04:00"),
        _raw_job(2, "Enterprise Account Executive", "New York City, NY", "2026-09-10T09:00:00-04:00"),
    ),
    _dept(
        "Technical Education",
        _raw_job(5097186008, "Full Stack Engineer, Education Labs",
                 "San Francisco, CA | New York City, NY | Seattle, WA", "2026-01-27T15:23:29-05:00"),
        _raw_job(5415529008, "Head of Technical Training",
                 "San Francisco, CA", "2026-09-04T12:11:40-04:00"),
    ),
    _dept(
        "AI Research & Engineering",
        _raw_job(3, "Research Engineer/Research Scientist, Pre-training",
                 "San Francisco, CA", "2026-09-01T09:00:00-04:00"),
        _raw_job(4, "Research Engineer, Production Model Post-Training",
                 "San Francisco, CA", "2026-09-02T09:00:00-04:00"),
    ),
]


def test_apple_parse_posted_with_prefix():
    assert apple_parse("Posted: Apr 15, 2026") == date(2026, 4, 15)


def test_apple_parse_posted_plain():
    assert apple_parse("Apr 15, 2026") == date(2026, 4, 15)


def test_apple_parse_posted_bad():
    assert apple_parse("") is None
    assert apple_parse("nonsense") is None


def test_anthropic_parse_published():
    assert anthropic_parse("2026-09-04T12:11:40-04:00") == date(2026, 9, 4)
    assert anthropic_parse(None) is None
    assert anthropic_parse("") is None
    assert anthropic_parse("nonsense") is None


def test_anthropic_matches_department_and_title():
    """Department OR title, on every run — and no pre/post-training research roles."""
    jobs = jobs_from_departments(BOARD)
    assert [j.title for j in jobs] == [
        "Developer Education Lead, Claude Platform",   # newest first; matched by title
        "Head of Technical Training",                  # matched by department
        "Full Stack Engineer, Education Labs",
    ]
    assert all(j.company == "Anthropic" for j in jobs)


def test_anthropic_title_match_needs_no_education_department():
    board = [
        _dept("Sales", _raw_job(1, "Enterprise Account Executive", "NYC", None)),
        _dept("People", _raw_job(2, "Lead Technical Instructor", "NYC", None)),
        _dept("Marketing & Brand", _raw_job(3, "Curriculum Designer", "SF", None)),
    ]
    assert sorted(j.title for j in jobs_from_departments(board)) == [
        "Curriculum Designer",
        "Lead Technical Instructor",
    ]


def test_anthropic_keeps_teaching_titles():
    for title in (
        "Lead Technical Instructor",
        "Head of Technical Training",
        "Software Engineer, Education",
        "Developer Education Lead, Claude Platform",
        "GTM Enablement Trainer, Claude Products",
        "Curriculum Designer",
        "Instructional Designer",
        "Head of Upskilling",
    ):
        assert is_education_role("Some Department", title), title


def test_anthropic_excludes_ml_training_titles():
    """'Training' at an AI lab is usually pre/post-training research, not teaching."""
    for title in (
        "Research Engineer/Research Scientist, Pre-training",
        "Research Engineer, Production Model Post-Training",
        "Pre-training Data Infrastructure Engineer",
        "Pretraining Distributed Systems Tech Lead",
        "Engineer, Model Training",
        "Training Infrastructure Engineer",
    ):
        assert not is_education_role("AI Research & Engineering", title), title


def test_anthropic_department_beats_the_ml_training_exclusion():
    """An education-department role isn't dropped for saying 'training data'."""
    assert is_education_role("Technical Education", "Engineer, Training Data Curation")


def test_anthropic_maps_job_fields():
    job = next(j for j in jobs_from_departments(BOARD) if j.job_id == "5097186008")
    assert job.title == "Full Stack Engineer, Education Labs"
    assert job.location == "San Francisco, CA | New York City, NY | Seattle, WA"
    assert job.url == "https://job-boards.greenhouse.io/anthropic/jobs/5097186008"
    assert job.posted_date == date(2026, 1, 27)
    assert job.dedup_key == "Anthropic::5097186008"


def test_anthropic_dedupes_job_listed_in_two_departments():
    shared = _raw_job(99, "Lead Technical Instructor", "New York City, NY", None)
    board = [_dept("Technical Education", shared), _dept("Education Labs", shared)]
    jobs = jobs_from_departments(board)
    assert len(jobs) == 1
    assert jobs[0].posted_date is None


def test_anthropic_skips_malformed_entries():
    board = [_dept(
        "Technical Education",
        {"id": None, "title": "No id", "absolute_url": "https://x/1"},
        {"id": 7, "title": "", "absolute_url": "https://x/7"},
        {"id": 8, "title": "No url"},
        _raw_job(9, "Software Engineer, Education", "San Francisco, CA", None),
    )]
    jobs = jobs_from_departments(board)
    assert [j.job_id for j in jobs] == ["9"]
    assert jobs[0].location == "San Francisco, CA"


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
