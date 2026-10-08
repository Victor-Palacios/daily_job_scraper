"""Pull an annual salary range out of a posting.

Boards disagree about where compensation lives. Ashby sometimes has a
structured `scrapeableCompensationSalarySummary` ("$180K - $290K") and often
nothing at all; Greenhouse and Workday bury it in the description, if it is
there at all. So this works on free text and is used for every source.

Absence is normal and is NOT a filter signal -- most postings never state pay.
`parse_salary` returns None when it cannot find a range it trusts, and callers
treat that as "unknown", not "too low".
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

# Hours per year used to annualize an hourly rate (40h x 52w).
HOURS_PER_YEAR = 2080

# Anything below this as an "annual" figure is a typo, a monthly number, or a
# stray dollar amount in prose (a budget, a prize, a discount).
MIN_CREDIBLE_ANNUAL = 30_000
# Anything above this is a contract value or total funding, not a salary.
MAX_CREDIBLE_ANNUAL = 2_000_000

# Boards double-escape their markup often enough that one unescape pass leaves
# entities behind: Anthropic's "$270,000 &mdash; $320,000" survived as a literal
# "&mdash;", so the range regex missed it and the job read as a flat $270,000.
_MAX_UNESCAPE_PASSES = 3


def _plain(text: str) -> str:
    """Resolve HTML entities, however many times they were escaped."""
    for _ in range(_MAX_UNESCAPE_PASSES):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text


_NUM = r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?"
_RANGE_RE = re.compile(_NUM + r"\s*(?:-|–|—|to)\s*" + _NUM, re.IGNORECASE)
_SINGLE_RE = re.compile(_NUM)
_HOURLY_RE = re.compile(r"(?:/|\bper\s+)\s*(?:hr|hour)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Salary:
    low: int
    high: int
    hourly: bool = False

    @property
    def top(self) -> int:
        return self.high


def _scale(raw: str, suffix: str | None) -> float | None:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    if suffix and suffix.lower() == "k":
        value *= 1_000
    elif suffix and suffix.lower() == "m":
        value *= 1_000_000
    return value


def _annualize(value: float, text_after: str) -> tuple[float, bool]:
    """Convert an hourly rate to a yearly figure when the text says /hr."""
    if _HOURLY_RE.match(text_after.lstrip()[:20]) or _HOURLY_RE.search(text_after[:24]):
        return value * HOURS_PER_YEAR, True
    return value, False


def _credible(value: float) -> bool:
    return MIN_CREDIBLE_ANNUAL <= value <= MAX_CREDIBLE_ANNUAL


def parse_salary(text: str) -> Salary | None:
    """Best-effort annual range from free text. None when nothing is credible."""
    if not text:
        return None
    flat = re.sub(r"\s+", " ", _plain(text))

    for m in _RANGE_RE.finditer(flat):
        low = _scale(m.group(1), m.group(2))
        high = _scale(m.group(3), m.group(4))
        if low is None or high is None:
            continue
        tail = flat[m.end():m.end() + 24]
        low, hourly = _annualize(low, tail)
        high, _ = _annualize(high, tail)
        if low > high:
            low, high = high, low
        if _credible(low) and _credible(high):
            return Salary(low=int(low), high=int(high), hourly=hourly)

    # No range: a lone figure still tells us roughly what the job pays.
    for m in _SINGLE_RE.finditer(flat):
        value = _scale(m.group(1), m.group(2))
        if value is None:
            continue
        value, hourly = _annualize(value, flat[m.end():m.end() + 24])
        if _credible(value):
            return Salary(low=int(value), high=int(value), hourly=hourly)

    return None


# What the role has to pay to be worth an email. Postings that state no range
# are kept regardless -- most never state one, so treating silence as "too low"
# would throw away the majority of real matches.
PRIMARY_FLOOR = 200_000
# Used only if NOTHING with a stated salary clears PRIMARY_FLOOR, so a quiet
# week still produces a digest instead of nothing.
FALLBACK_FLOOR = 180_000


def clears(salary: Salary | None, floor: int) -> bool:
    """Does this posting's range reach `floor`? Unknown salary always passes.

    The top of the range is the test, not the bottom: a posting listing
    "$180K - $290K" is a job that can pay $290K, and a band that wide is
    normally set by level rather than being a real cap on the role.
    """
    if salary is None:
        return True
    return salary.top >= floor


def apply_floor(jobs: list, floor: int = PRIMARY_FLOOR,
                fallback: int = FALLBACK_FLOOR) -> tuple[list, int]:
    """Filter to jobs clearing `floor`, dropping to `fallback` if none do.

    Returns the kept jobs and the floor actually applied. Only postings with a
    stated salary count when deciding whether to fall back -- unknown-salary
    jobs pass either way, so letting them satisfy the primary floor would mean
    never falling back at all.
    """
    priced = [j for j in jobs if j.salary is not None]
    if any(clears(j.salary, floor) for j in priced):
        return [j for j in jobs if clears(j.salary, floor)], floor
    return [j for j in jobs if clears(j.salary, fallback)], fallback
