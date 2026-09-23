# Daily Job Scraper

Automated GitHub Actions pipeline that watches [Anthropic's careers page](https://www.anthropic.com/careers/jobs) for new **Education** roles and emails the links via Gmail SMTP.

## Sources

| Source | Status | Filter |
| --- | --- | --- |
| Anthropic | **active** | Greenhouse "Technical Education" department |
| Apple | deactivated | — |
| Google | deactivated | — |

Apple and Google are off but not deleted: `src/scrapers/apple.py` and `src/scrapers/google.py` are still there. To bring one back, import it in `src/main.py` and add it to `SCRAPERS`, then restore the commented-out `playwright install` step in `.github/workflows/scrape.yml` — those two scrapers need a browser, the Anthropic one doesn't.

## How it works

- Runs 4x per day (00:00, 06:00, 12:00, 18:00 UTC) via `.github/workflows/scrape.yml`.
- `anthropic.com/careers/jobs` is a server-rendered view of Anthropic's Greenhouse board — every "Apply" link on it points at `job-boards.greenhouse.io`, and the page embeds the same departments payload. So the scraper reads the board API directly (`boards-api.greenhouse.io/v1/boards/anthropic/departments?render_as=list`) instead of driving a headless browser. No Playwright, no CSS selectors to rot, one request per run.
- Education roles are selected by **department**, matching any department whose name contains "education" — today that's "Technical Education", the same grouping the careers page shows. Selecting by department rather than by title keyword is what keeps `Technical Documentation and Content Engineer, Claude Docs` in (no education keyword in its title) and education-adjacent Sales roles out.
- Greenhouse exposes `first_published`, so every job carries a real posting date.
- Dedupes against a rolling seen-jobs store (`.state/seen_jobs.json`); a job is "new" if its stable Greenhouse ID hasn't been seen within the store's TTL. Skips the email entirely when nothing new.

## Local setup

```bash
python3 -m venv djs
source djs/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with your Gmail + app password
```

`playwright` stays in `requirements.txt` so the deactivated scrapers still import; the active path never launches it. If you re-enable Apple or Google, also run `playwright install chromium`.

Check what it would send without emailing:

```bash
python -m src.main --dry-run
```

## Gmail app password

1. Enable 2FA on your Google account.
2. Generate an app password: https://myaccount.google.com/apppasswords
3. Use the 16-character password (spaces optional) as `GMAIL_APP_PASSWORD`.

## GitHub deployment

```bash
gh repo create daily_job_scraper --private --source=. --push
```

Then in the repo's **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
| --- | --- |
| `GMAIL_USER` | `you@gmail.com` |
| `GMAIL_APP_PASSWORD` | `xxxx xxxx xxxx xxxx` |

Trigger a test run from the **Actions** tab → **Daily Job Scrape** → **Run workflow**.

## Gotchas

- **60-day inactivity rule**: GitHub automatically disables scheduled workflows if the repo has no commits for 60 days. Either push a small change periodically or add a keepalive action.
- **Department renames**: The Anthropic scraper keys off a department name containing "education". If that department is renamed to something else entirely or folded into another org, the scraper falls back to a narrow title keyword match (`education`, `instructor`, `curriculum`, `technical training`, …) and logs a warning, rather than silently returning 0. The fallback is approximate — if you see that warning, check the board and update `DEPARTMENT_RE`.
- **Site DOM changes**: Only applies to the deactivated Apple/Google scrapers — they parse CSS selectors and will silently return 0 jobs if either site reworks its markup. The Actions logs show the "parsed N jobs" line for each company — watch for sudden drops.
- **Cron drift**: GitHub cron jobs can be delayed by several minutes during high load. Don't schedule critical work to the exact minute.
