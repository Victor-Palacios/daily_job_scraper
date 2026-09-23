# Daily Job Scraper

Automated GitHub Actions pipeline that watches [Anthropic's careers page](https://www.anthropic.com/careers/jobs) for new **Education** roles and emails the links via Gmail SMTP.

## Sources

| Source | Status | Filter |
| --- | --- | --- |
| Anthropic | **active** | Education department **or** education/instructor/training in the title |
| Apple | deactivated | — |
| Google | deactivated | — |

Apple and Google are off but not deleted: `src/scrapers/apple.py` and `src/scrapers/google.py` are still there. To bring one back, import it in `src/main.py` and add it to `SCRAPERS`, then restore the commented-out `playwright install` step in `.github/workflows/scrape.yml` — those two scrapers need a browser, the Anthropic one doesn't.

## How it works

- Runs 4x per day (00:00, 06:00, 12:00, 18:00 UTC) via `.github/workflows/scrape.yml`.
- `anthropic.com/careers/jobs` is a server-rendered view of Anthropic's Greenhouse board — every "Apply" link on it points at `job-boards.greenhouse.io`, and the page embeds the same departments payload. So the scraper reads the board API directly (`boards-api.greenhouse.io/v1/boards/anthropic/departments?render_as=list`) instead of driving a headless browser. No Playwright, no CSS selectors to rot, one request per run.
- A job is kept if **either** test passes, and both run on every pass:
  1. **Department** contains "education" — today "Technical Education", the same grouping the careers page shows. This is what catches `Technical Documentation and Content Engineer, Claude Docs`, which has no education keyword in its title.
  2. **Title** matches `education`, `educator`, `instructor`, `instruction(al)`, `teaching`, `teacher`, `trainer`, `training`, `curriculum`, `pedagog*`, or `upskilling`. This catches teaching roles filed under other orgs — e.g. `Developer Education Lead, Claude Platform` under Sales.
- One exception subtracts from the title test: "training" at an AI lab usually means **pre-training / post-training research**, not teaching. `ML_TRAINING_RE` drops those (`Pre-training Data Infrastructure Engineer`, `Research Engineer, Production Model Post-Training`, …) — 5 false positives on today's board. A department hit is never filtered this way, so an education-team role that happens to say "training data" still comes through.
- Both regexes live at the top of `src/scrapers/anthropic.py` (`DEPARTMENT_RE`, `TITLE_RE`, `ML_TRAINING_RE`) and are the only thing to edit to widen or narrow the net.
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
- **Nothing matched**: If the board loads but no role passes either test, the run logs a loud `no education roles matched` warning instead of quietly reporting 0. That means a reorg or a rename — check the careers page against `DEPARTMENT_RE` / `TITLE_RE`.
- **Emails only cover *new* roles**: the seen-store means each role is emailed once. A run where nothing is new sends no email at all — that's success, not failure. To force a full digest (e.g. to test), run with `--reset-store`.
- **Site DOM changes**: Only applies to the deactivated Apple/Google scrapers — they parse CSS selectors and will silently return 0 jobs if either site reworks its markup. The Actions logs show the "parsed N jobs" line for each company — watch for sudden drops.
- **Cron drift**: GitHub cron jobs can be delayed by several minutes during high load. Don't schedule critical work to the exact minute.
