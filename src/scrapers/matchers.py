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
    r"enablement|facilitator|workshop|academy|bootcamp|adoption|"
    # Stage-facing variants. An "Applied AI Evangelism Director" is the same
    # job as a technical instructor -- build the thing, then demo it live to a
    # room -- but none of the words above appear in that title.
    r"evangelis\w*|advocate|keynote|technical marketing)\b",
    re.IGNORECASE,
)

# "advocacy" is deliberately absent: it matches Anthropic's policy-advocacy
# roles, which are lobbying, not teaching. "advocate" alone catches Developer
# Advocate without them. Also absent: "forward deployed" and "solutions
# engineer", which nearly doubled the shortlist with deployment and pre-sales
# engineering rather than anything stage-facing.

# "Training" at an AI company usually means pre/post-training research, not
# teaching. Subtracted from the title signal on every source.
ML_TRAINING_RE = re.compile(
    r"\b(pre|post|mid)[\s-]?training\b|\bpretraining\b|\bposttraining\b|\bmidtraining\b|"
    r"\bmodel training\b|\btraining (data|infra\w*|cluster|stack|runtime|platform|compute)\b",
    re.IGNORECASE,
)

# Teaching roles whose subject plainly is not AI. Checked on the title only,
# so an AI role that merely mentions one of these in passing is unaffected.
NON_AI_SUBJECT_RE = re.compile(
    r"\blanguage (training|instruction|instructor|specialist)\b|"
    r"\b(japanese|spanish|mandarin|french|german|english) language\b",
    re.IGNORECASE,
)

CLAUDE_RE = re.compile(r"\b(claude|anthropic)\b", re.IGNORECASE)

# Broader than CLAUDE_RE: is this job about AI at all? Used where naming a
# vendor is not required, because a company selling its own AI platform
# describes the platform, not the model under it. Intapp's Applied AI
# Evangelism Director never says Claude -- the product is "Celeste".
AI_RE = re.compile(
    r"\b(ai|a\.i\.|artificial intelligence|genai|gen ai|generative|llm|"
    r"large language model|machine learning|agentic|agent|copilot|chatgpt|"
    r"gpt-?\d*|gemini|bedrock|claude|anthropic)\b",
    re.IGNORECASE,
)

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
#
# Set from measured boards, because a firm with a real Claude practice looks
# superficially like one with Claude boilerplate. Mention counts per sampled
# non-teaching posting:
#
#   Caylent    [4, 4, 4, 4, 4, 6]     ratio 1.00  -- boilerplate (uniform, low)
#   CodePath   [1, 1, 1, 5, 2, 1]     ratio 1.00  -- boilerplate
#   NewRocket  [0, 0, 23, 23, 4, 0]   ratio 0.50  -- a Claude practice, not a template
#
# NewRocket's hits are genuine Claude reqs (Agentic AI Architect-Anthropic) next
# to ServiceNow reqs that never mention it -- bimodal, where a template is
# uniform. At 0.5 this was misread as boilerplate, which quietly stopped
# descriptions counting on the single most relevant board. 0.8 sits in the gap.
BOILERPLATE_RATIO = 0.8
MIN_BASELINE_SAMPLE = 3

# AI_RE is far more common in prose than CLAUDE_RE, so the bar for "this
# posting is really about AI" is higher than the two mentions Claude needs.
MIN_AI_CONTENT_MENTIONS = 5


def looks_like_boilerplate(samples: list[str], pattern: "re.Pattern | None" = None) -> bool:
    """True if the subject shows up in enough unrelated postings to be template text.

    `samples` are descriptions of postings the matcher did NOT shortlist, so a
    hit in them is by definition not about the job.

    `pattern` is the matcher's own subject, because the answer differs by
    subject on the same board. Booz Allen appends a "Candidate AI Usage Policy"
    to every req, which is boilerplate for AI_RE but invisible to CLAUDE_RE.
    Defaults to CLAUDE_RE for callers that predate the parameter.
    """
    if len(samples) < MIN_BASELINE_SAMPLE:
        return False
    rx = pattern or CLAUDE_RE
    hits = sum(1 for s in samples if rx.search(s or ""))
    return hits / len(samples) >= BOILERPLATE_RATIO


class Matcher(ABC):
    """Decides whether a posting belongs in the digest."""

    name: str
    needs_content: bool = False
    # The regex a scraper should use when testing a board for subject
    # boilerplate; see looks_like_boilerplate.
    subject_re: "re.Pattern" = None

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
    subject_re = CLAUDE_RE

    def shortlist(self, title: str, department: str) -> bool:
        if EDUCATION_DEPARTMENT_RE.search(department or ""):
            return True
        return bool(TEACHING_RE.search(title or "")) and not ML_TRAINING_RE.search(title or "")


class ClaudeTeaching(Matcher):
    """Partner/vendor boards: a teaching role AND Claude as the subject."""

    name = "claude-teaching"
    needs_content = True
    subject_re = CLAUDE_RE

    def shortlist(self, title: str, department: str) -> bool:
        haystack = f"{title or ''} {department or ''}"
        if not PARTNER_TEACHING_RE.search(haystack):
            return False
        if NON_AI_SUBJECT_RE.search(title or ""):
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


class AiTeaching(Matcher):
    """A teaching or evangelism role about AI, with no vendor named.

    Looser than ClaudeTeaching on purpose. At a company whose own product is
    the AI, the posting advertises the product rather than the model beneath
    it, so demanding the word "Claude" silently excludes exactly the roles
    worth seeing.
    """

    name = "ai-teaching"
    needs_content = True
    subject_re = AI_RE

    def shortlist(self, title: str, department: str) -> bool:
        haystack = f"{title or ''} {department or ''}"
        if not PARTNER_TEACHING_RE.search(haystack):
            return False
        if NON_AI_SUBJECT_RE.search(title or ""):
            return False
        return not ML_TRAINING_RE.search(title or "")

    def confirm(
        self, title: str, department: str, content: str, content_trusted: bool = True
    ) -> bool:
        if AI_RE.search(f"{title or ''} {department or ''}"):
            return True
        if not content_trusted:
            return False
        # Every tech posting says "AI" once now; a job actually about AI says
        # it throughout.
        return len(AI_RE.findall(content or "")) >= MIN_AI_CONTENT_MENTIONS


AI_TEACHING = AiTeaching()


class TeachingAtAiCompany(Matcher):
    """A teaching or evangelism role, where the COMPANY is the AI signal.

    For a curated set of companies whose product is itself AI -- Anthropic
    partners, agentic coding tools, Intapp -- asking "is this posting about
    AI?" is uninformative, because every posting is. Worse, it actively
    backfires: AI appears in all of them, so the boilerplate baseline
    correctly marks descriptions useless, after which only AI-titled roles
    survive and genuine ones like "Technical Education Specialist" and
    "Developer Advocate" are dropped.

    So no content test at all. Teaching at an AI company is AI teaching, and
    the curation in src/sources.py is what makes that true.
    """

    name = "teaching-at-ai-company"
    needs_content = False
    subject_re = AI_RE

    def shortlist(self, title: str, department: str) -> bool:
        haystack = f"{title or ''} {department or ''}"
        if not PARTNER_TEACHING_RE.search(haystack):
            return False
        if NON_AI_SUBJECT_RE.search(title or ""):
            return False
        return not ML_TRAINING_RE.search(title or "")


TEACHING_AT_AI_COMPANY = TeachingAtAiCompany()
