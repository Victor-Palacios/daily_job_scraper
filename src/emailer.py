"""Send a digest email of today's new jobs via Gmail SMTP."""
from __future__ import annotations

import logging
import smtplib
from collections import defaultdict
from datetime import date
from email.message import EmailMessage
from html import escape

from .config import Config
from .scrapers.base import Job

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_job_digest(jobs: list[Job], cfg: Config) -> None:
    """Build and send a single HTML digest. No-op if `jobs` is empty."""
    if not jobs:
        log.info("No jobs to email; skipping send.")
        return

    today = date.today().isoformat()
    subject = f"[Daily Jobs] {len(jobs)} new role(s) — {today}"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.gmail_user
    msg["To"] = cfg.recipient
    msg.set_content(_plain_body(jobs))
    msg.add_alternative(_html_body(jobs, today), subtype="html")

    log.info("Sending email to %s with %d jobs", cfg.recipient, len(jobs))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(cfg.gmail_user, cfg.gmail_app_password)
        server.send_message(msg)
    log.info("Email sent.")


def _group_by_company(jobs: list[Job]) -> dict[str, list[Job]]:
    grouped: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        grouped[job.company].append(job)
    return grouped


def _plain_body(jobs: list[Job]) -> str:
    lines = ["New roles posted today:", ""]
    for company, items in _group_by_company(jobs).items():
        lines.append(f"== {company} ({len(items)}) ==")
        for j in items:
            loc = f" — {j.location}" if j.location else ""
            lines.append(f"- {j.title}{loc}")
            lines.append(f"  {j.url}")
        lines.append("")
    return "\n".join(lines)


def _html_body(jobs: list[Job], today: str) -> str:
    parts = [
        "<html><body style='font-family: -apple-system, sans-serif; line-height: 1.5;'>",
        f"<h2>New roles — {escape(today)}</h2>",
    ]
    for company, items in _group_by_company(jobs).items():
        parts.append(f"<h3>{escape(company)} ({len(items)})</h3><ul>")
        for j in items:
            loc = f" — <i>{escape(j.location)}</i>" if j.location else ""
            parts.append(
                f'<li><a href="{escape(j.url)}">{escape(j.title)}</a>{loc}</li>'
            )
        parts.append("</ul>")
    parts.append("</body></html>")
    return "".join(parts)
