"""Which postings each source cares about.

A matcher runs in two passes so scrapers don't pay for descriptions they don't
need:

    shortlist(title, department)           cheap, from the board listing alone
    confirm(title, department, content)    only for shortlisted jobs

`needs_content` tells the scraper whether confirm() actually reads the
description. Greenhouse's listing has no description, so a content-hungry
matcher costs one extra request per shortlisted job; Ashby ships
`descriptionPlain` in the listing, so it is free there.

Two matchers exist because the sources are not alike:

* Anthropic's board is all Claude, so the question is only "is this a teaching
  role" -- ANTHROPIC_EDUCATION answers it from the department and title.
* Every other board is mostly unrelated work, so a teaching title alone is not
  enough. CLAUDE_TEACHING requires a teaching signal AND evidence that Claude
  is actually the subject.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

# Anthropic files education roles under "Technical Education". Matching the word
# keeps a rename to plain "Education" (or "Education Labs") working.
EDUCATION_DEPARTMENT_RE = re.compile(r"\beducation\b", re.IGNORECASE)

# Teaching signal on Anthropic's own board.
TEACHING_RE = re.compile(
    r"\b(education|educational|educator|instructor|instruction|instructional|"
    r"teaching|teacher|trainer|training|curriculum|pedagog\w*|upskilling)\b",
    re.IGNORECASE,
)

# Teaching signal on partner/vendor boards. Wider than TEACHING_RE: "enablement",
# "facilitator", "workshop" and "academy" are how training vendors and Anthropic
# partners name these jobs. They are too noisy for Anthropic's own board (where
# "enablement" is GTM vocabulary and pulls in sales roles), but they are safe
# here because CLAUDE_RE has to agree before anything is kept.
PARTNER_TEACHING_RE = re.compile(
    r"\b(education|educational|educator|instructor|instruction|instructional|"
    r"teaching|teacher|trainer|training|curriculum|pedagog\w*|upskilling|"
    r"enablement|facilitator|workshop|academy|bootcamp|adoption)\b",
    re.IGNORECASE,
)

# "Training" at an AI company usually means pre/post-training research, not
# teaching. Subtracted from the title signal on every source.
ML_TRAINING_RE = re.compile(
    r"\b(pre|post)[\s-]?training\b|\bpretraining\b|\bposttraining\b|"
    r"\bmodel training\b|\btraining (data|infra\w*|cluster|stack|runtime|platform|compute)\b",
    re.IGNORECASE,
)

CLAUDE_RE = re.compile(r"\b(claude|anthropic)\b", re.IGNORECASE)

# One passing Claude mention is usually boilerplate, so require two in the body.
# This is a weak signal on its own -- Caylent's company blurb ("a charter member
# of Anthropic's Claude Partner Network") mentions Claude four times in postings
# that have nothing to do with Claude, out-scoring genuine matches. The real
# defense is the per-board boilerplate baseline the scrapers compute; see
# `looks_like_boilerplate`. A hit in the title or department skips both checks.
MIN_CONTENT_MENTIONS = 2

# If this fraction of a board's postings mention Claude, the mention is part of
# the company template rather than the job, so descriptions stop being evidence
# for that board and only the title and department count.
BOILERPLATE_RATIO = 0.5
MIN_BASELINE_SAMPLE = 3


def looks_like_boilerplate(samples: list[str]) -> bool:
    """True if Claude shows up in enough unrelated postings to be company boilerplate.

    `samples` are descriptions of postings the matcher did NOT shortlist, so any
    Claude mention in them is by definition not about the job.
    """
    if len(samples) < MIN_BASELINE_SAMPLE:
        return False
    hits = sum(1 for s in samples if CLAUDE_RE.search(s or ""))
    return hits / len(samples) >= BOILERPLATE_RATIO


class Matcher(ABC):
    """Decides whether a posting belongs in the digest."""

    name: str
    needs_content: bool = False

    @abstractmethod
    def shortlist(self, title: str, department: str) -> bool:
        """Cheap pass over the board listing."""

    def confirm(
        self, title: str, department: str, content: str, content_trusted: bool = True
    ) -> bool:
        """Second pass. Default: anything shortlisted is kept.

        `content_trusted` is False when the scraper has established that this
        board mentions Claude in every posting, making the description useless
        as evidence.
        """
        return True


class AnthropicEducation(Matcher):
    """Anthropic's own board: department OR teaching title, no content needed."""

    name = "anthropic-education"
    needs_content = False

    def shortlist(self, title: str, department: str) -> bool:
        if EDUCATION_DEPARTMENT_RE.search(department or ""):
            return True
        return bool(TEACHING_RE.search(title or "")) and not ML_TRAINING_RE.search(title or "")


class ClaudeTeaching(Matcher):
    """Partner/vendor boards: a teaching role AND Claude as the subject."""

    name = "claude-teaching"
    needs_content = True

    def shortlist(self, title: str, department: str) -> bool:
        haystack = f"{title or ''} {department or ''}"
        if not PARTNER_TEACHING_RE.search(haystack):
            return False
        return not ML_TRAINING_RE.search(title or "")

    def confirm(
        self, title: str, department: str, content: str, content_trusted: bool = True
    ) -> bool:
        if CLAUDE_RE.search(f"{title or ''} {department or ''}"):
            return True
        if not content_trusted:
            return False
        return len(CLAUDE_RE.findall(content or "")) >= MIN_CONTENT_MENTIONS


ANTHROPIC_EDUCATION = AnthropicEducation()
CLAUDE_TEACHING = ClaudeTeaching()
