# Daily Job Scraper

Automated GitHub Actions pipeline that watches job boards for roles **teaching and evangelising AI** — live instruction, enablement, demo and developer-advocacy work — and emails the links via Gmail SMTP.

## Sources

Defined in [`src/sources.py`](src/sources.py) — one line per board.

| Source | Board | Matcher |
| --- | --- | --- |
| Anthropic | `greenhouse/anthropic` | `anthropic-education` |
| NewRocket | `greenhouse/highmetric` | `teaching-at-ai-company` |
| Caylent | `greenhouse/caylent` | `teaching-at-ai-company` |
| Correlation One | `greenhouse/correlationone` | `ai-teaching` |
| DataCamp | `greenhouse/datacamp` | `ai-teaching` |
| CodePath | `greenhouse/codepath` | `ai-teaching` |
| General Assembly | `greenhouse/generalassembly` | `ai-teaching` |
| Cursor | `ashby/cursor` | `teaching-at-ai-company` |
| Replit | `ashby/replit` | `teaching-at-ai-company` |
| Cognition | `ashby/cognition` | `teaching-at-ai-company` |
| Factory | `ashby/factory` | `teaching-at-ai-company` |
| Notion | `ashby/notion` | `teaching-at-ai-company` |
| Intapp | `workday/intapp.wd1` | `teaching-at-ai-company` |
| Salesforce | `workday/salesforce.wd12` | `ai-teaching` |
| Booz Allen | `workday/bah.wd1` | `ai-teaching` |
| Apple, Google | — | deactivated |

### Matchers

Which test a board gets depends on what else that board sells.

- **`anthropic-education`** — Anthropic's own board. Every posting is about Claude, so the only question is whether the role teaches.
- **`teaching-at-ai-company`** — for companies whose product *is* AI. No content test at all: at Cursor or Intapp every posting mentions AI, so asking "is this about AI?" carries no information, and worse, it backfires. AI in all postings means the boilerplate baseline correctly marks descriptions useless, after which only AI-*titled* roles survive and real ones like `Technical Education Specialist` and `Developer Advocate` get dropped. The curation in `src/sources.py` is what makes "teaching here is AI teaching" true.
- **`ai-teaching`** — for companies that teach many subjects (bootcamps) or sell many things (Salesforce, Booz Allen). A teaching title plus proof from the description that the role is actually about AI.
- **`claude-teaching`** — stricter still; Claude must be the subject. Unused today, kept for any board that turns out too noisy.

Apple and Google are off but not deleted: `src/scrapers/apple.py` and `src/scrapers/google.py` are still there. To bring one back, import it in `src/main.py` and add it to `SCRAPERS`, then restore the commented-out `playwright install` step in `.github/workflows/scrape.yml` — those two need a browser, none of the active sources do.

### Adding a company

One line in `src/sources.py`, if they run Greenhouse or Ashby. Find the board token in their careers URL or "Apply" links, and check it resolves first:

```bash
curl -s "https://boards-api.greenhouse.io/v1/boards/<token>/departments?render_as=list" | head -c 200
curl -s "https://api.ashbyhq.com/posting-api/job-board/<token>" | head -c 200
```

Workday career sites look like SPAs but are backed by the same kind of unauthenticated JSON API the page itself calls, so they need no browser either — an earlier version of this README wrongly ruled them out. They do need care: Booz Allen lists ~2000 reqs and Salesforce ~1500, so `src/sources.py` gives those boards `search_terms` and the scraper queries server-side instead of walking them, capped by `MAX_DETAIL_FETCHES`.

Still absent: SmartRecruiters and bespoke SPAs, and firms too small for an ATS at all (ClaudeReadiness, OneWave AI) have no board to point at.

## Pay floor

Roles are dropped when the posting states a range whose **top** is under **$200,000**. The top rather than the bottom, because a band as wide as "$180K - $290K" is set by level and is not a real cap on the role.

Two rules keep this from silently emptying the digest:

- **Unknown pay always passes.** Most postings state nothing; treating silence as "too low" would discard the majority of genuine matches, Anthropic's own instructor roles among them.
- **The floor falls back to $180,000** if *nothing with a stated range* clears $200,000, so a quiet week still produces a digest. Unknown-salary roles do not count towards that decision — they pass either way, so letting them satisfy the primary floor would mean never falling back.

Hourly rates are annualised at 2080h, and figures outside $30k–$2M are ignored as prize money, funding rounds or typos.

## How it works

- Runs 4x per day (00:00, 06:00, 12:00, 18:00 UTC) via `.github/workflows/scrape.yml`.
- Every source is a **public JSON job-board API**, not a careers page. `anthropic.com/careers/jobs`, for instance, is just a server-rendered view of Anthropic's Greenhouse board — its "Apply" links point straight at `job-boards.greenhouse.io`. Reading the API directly means no headless browser and no CSS selectors to rot.
- Matching runs in two passes so descriptions are only fetched when they're needed (`src/scrapers/matchers.py`):
  1. `shortlist(title, department)` — cheap, from the listing alone.
  2. `confirm(title, department, content)` — only for shortlisted jobs. Greenhouse's listing has no description, so this costs one extra request per shortlisted job; Ashby ships `descriptionPlain` in the listing, so it's free.
- **Anthropic** uses the `anthropic-education` matcher: the whole board is Claude, so the only question is whether a role teaches. Education department, or a teaching title anywhere else.
- **Every other board** uses `claude-teaching`: a teaching signal in the title or department, AND evidence Claude is the subject. Both halves are needed — these boards are mostly unrelated work.
- Two traps the matchers are built around, both found by running against the real boards:
  - **"Training" at an AI company usually means pre/post-training research.** `ML_TRAINING_RE` subtracts those (`Pre-training Data Infrastructure Engineer`, …) — 5 false positives on Anthropic's board alone. A department hit is never filtered this way, so an education-team role saying "training data" survives.
  - **Company boilerplate mentions Claude in every posting.** Caylent's blurb ("a charter member of Anthropic's Claude Partner Network") names Claude 4× in reqs that have nothing to do with it — out-scoring genuine matches, so counting mentions cannot fix it. Instead each scraper samples postings the matcher *rejected*: if most of them mention Claude, the description carries no signal for that board and only the title and department count. This dropped 5 Caylent Databricks roles while keeping Correlation One's instructor role, whose only Claude mention is in the body.
- Both regex sets live at the top of `src/scrapers/matchers.py` and are the only thing to edit to widen or narrow the net.
- Greenhouse and Ashby both expose a publish date, so every job carries a real posting date.
- Dedupes twice: within a run (`dedupe_jobs` collapses one role posted under several ids — DataCamp lists the same req 4× a minute apart — keeping the earliest), and across runs against a rolling seen-jobs store (`.state/seen_jobs.json`). Skips the email entirely when nothing new.

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
- **Nothing matched**: each source logs `N shortlisted -> M matched`, and says so explicitly when a board loaded but nothing matched. A source that silently drops to 0 and stays there means a department rename or a board-token change — check it against `src/scrapers/matchers.py`.
- **Pay parsing is best-effort**: it reads free text, so a posting that buries pay in an image or an external benefits page reads as "not stated" and is kept. Worth knowing the direction of the error: the floor only ever drops roles it can *prove* are below it.
- **Board tokens can change**: a company migrating ATS (or rebranding, as NewRocket did — its board is still `highmetric`) breaks that one source and logs `board request failed`. The other sources are unaffected; each scraper returns 0 on failure rather than aborting the run.
- **Emails only cover *new* roles**: the seen-store means each role is emailed once. A run where nothing is new sends no email at all — that's success, not failure. To force a full digest (e.g. to test), run with `--reset-store`.
- **Site DOM changes**: Only applies to the deactivated Apple/Google scrapers — they parse CSS selectors and will silently return 0 jobs if either site reworks its markup. The Actions logs show the "parsed N jobs" line for each company — watch for sudden drops.
- **Cron drift**: GitHub cron jobs can be delayed by several minutes during high load. Don't schedule critical work to the exact minute.
