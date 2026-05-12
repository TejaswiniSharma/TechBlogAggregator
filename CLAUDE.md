# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the web app locally (http://localhost:5001)
python3 web/app.py

# Fetch articles from all configured blogs
python3 run_fetch.py

# AI-tag unanalyzed articles (requires ANTHROPIC_API_KEY env var)
export ANTHROPIC_API_KEY="sk-ant-..."
python3 run_ai_tag.py

# Run all tests
pytest

# Run a single test file
pytest tests/test_storage.py

# Run a single test by name
pytest tests/test_storage.py::test_add_articles_dedup

# Install dependencies (includes Playwright chromium for LinkedIn scraping)
pip install -r requirements.txt
playwright install chromium
```

## Architecture

The system is a pipeline of four subsystems:

```
RSS/Playwright → Fetcher → SQLite → AI Tagger → Flask Website
```

**Subsystem 1 — Fetcher** (`fetcher/`, `run_fetch.py`)
- `rss_fetcher.py`: Fetches via feedparser; normalizes all RSS/Atom formats into a fixed article dict schema. Determines fetch strategy from config: `rss_url` → feedparser, `scrape_url` → Playwright.
- `web_scraper.py`: Playwright headless browser for JS-rendered blogs (LinkedIn, Uber, DoorDash, Shopify).
- `topic_tagger.py`: Keyword-based tagger that runs at fetch time — fast but coarse.
- `storage.py`: Single persistence layer for the whole system. All reads/writes go through here. Uses `INSERT OR IGNORE` by URL for dedup. Rebuilds FTS5 index after batch inserts.

**Subsystem 2 — AI Tagger** (`ai_tagger/`, `run_ai_tag.py`)
- Sends articles to `claude-haiku-4-5-20251001` for structured extraction (problem, solution, concepts, refined tags). Returns JSON; falls back gracefully on parse errors.
- Only processes articles with `status = 'new'` — safe to re-run.

**Subsystem 3 — Config** (`config/blogs.py`)
- One dict per blog. Adding a blog = adding one dict. The `tags_hint` field is passed to Claude as context for AI tagging.

**Subsystem 4 — Web App** (`web/app.py`, `web/templates/`)
- Flask app on port 5001. Uses WAL mode SQLite with per-request connections (Flask `g`).
- FTS5 virtual tables (`articles_fts`, `notes_fts`) are created and rebuilt lazily in `_ensure_fts_tables()` — called on every connection open.
- Homepage groups by `DATE(fetched_at)` (cron run), not publish week. Archives shows everything older than the 2 most recent fetch dates.
- API endpoints: `POST /api/bookmark`, `POST /api/notes`, `DELETE /api/notes/<id>`, `GET /api/notes/search`. All write endpoints are rate-limited by IP via flask-limiter.

## Database Schema

SQLite at `data/techblogs.db`. Key tables:
- `articles` — primary store; `id` is md5(url)[:12]; `tags`/`ai_concepts` are JSON strings
- `notes` — per-article personal notes; FK to `articles.id`
- `articles_fts` — FTS5 content table backed by `articles` (title, summary, ai_problem, ai_solution)
- `notes_fts` — FTS5 content table backed by `notes` (content)

FTS5 content tables require manual sync: when updating/deleting notes, you must send a `'delete'` command with the OLD content before inserting the new row (see `save_note()` in `web/app.py`).

## Tests

`tests/conftest.py` provides:
- `tmp_db` fixture: patches `storage.DB_FILE` to a temp path via `monkeypatch`
- `flask_client` fixture: full Flask test client with pre-seeded articles across multiple fetch dates (needed because archives skips the 2 most recent dates)
- `make_article()` helper: builds complete article dicts with all required fields

## Deployment

Production runs on AWS EC2 with Gunicorn + Nginx. The weekly cron (`scripts/weekly_update.sh`) runs fetch → AI tag → email notify. Service config is in `deploy/`.
