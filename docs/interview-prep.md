# Distributed Readings — System Design Interview Walkthrough

> A tech blog aggregation system that collects, analyzes, and curates engineering blog posts from 7 major tech companies. Built as a personal learning tool for system design interview prep.

**Live on:** https://distributedreadings.uk (AWS EC2 + Cloudflare)
**Stack:** Python, Flask, SQLite, Nginx, Gunicorn, Claude AI, AWS SES, GitHub Actions

---

## 1. The Elevator Pitch

"I built a system that automatically fetches engineering blog posts from companies like Netflix, Airbnb, and Meta every week, runs them through an AI pipeline to extract system design concepts, and serves them on a curated website. It's deployed on AWS with a full CI/CD pipeline — push to main runs tests and auto-deploys to EC2."

---

## 2. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Weekly Cron Job                         │
│              (Monday 8 AM — weekly_update.sh)               │
└──────┬──────────────────┬───────────────────┬───────────────┘
       │                  │                   │
       v                  v                   v
┌──────────────┐  ┌───────────────┐  ┌────────────────┐
│  Subsystem 1 │  │  Subsystem 2  │  │  Notification  │
│  RSS Fetcher │  │  AI Tagger    │  │  AWS SES Email │
│  Web Scraper │  │  Claude API   │  │                │
└──────┬───────┘  └───────┬───────┘  └────────────────┘
       │                  │
       v                  v
┌─────────────────────────────────────┐
│         SQLite Database             │
│    (WAL mode, indexed, normalized)  │
└──────────────────┬──────────────────┘
                   │
                   v
┌─────────────────────────────────────┐
│         Subsystem 4: Website        │
│   Flask + Gunicorn + Nginx (EC2)    │
│   Filter by topic / company         │
│   Bookmarks, Notes, Archives        │
└─────────────────────────────────────┘
                   │
                   v
┌─────────────────────────────────────┐
│         CI/CD Pipeline              │
│  GitHub Actions → Test → Deploy     │
└─────────────────────────────────────┘
```

---

## 3. Subsystem 1 — Data Ingestion

### What It Does
Fetches new articles from 7 tech company blogs every week.

### Two Fetching Strategies

**RSS Fetcher** (`fetcher/rss_fetcher.py`)
- Uses `feedparser` library to parse RSS/Atom feeds
- Sources: Netflix, Airbnb, Cloudflare, AWS, Meta, Dropbox
- Normalizes different feed formats into a unified schema: `{id, title, url, summary, company, published_date, tags}`
- Strips HTML from summaries using regex
- Generates deterministic article IDs via MD5 hash of URL (for deduplication)

**Web Scraper** (`fetcher/web_scraper.py`)
- Used for JavaScript-rendered blogs (LinkedIn) where RSS isn't available
- Uses Playwright with headless Chromium
- Waits for `networkidle` state to capture lazy-loaded content
- Filters URLs by depth pattern to identify article pages vs. navigation pages

### Design Decisions

| Decision | Reasoning |
|----------|-----------|
| Two fetcher types (RSS vs Scraper) | RSS is preferred (lightweight, structured), but LinkedIn requires JS rendering. Adapter pattern ensures both return identical schemas. |
| MD5 hash for article ID | Deterministic — same URL always produces same ID. Enables deduplication across runs without database lookups at fetch time. |
| HTML stripping at ingestion | Clean data at the boundary. Downstream systems (AI tagger, website) never deal with raw HTML in summaries. |

### Follow-Up Questions & Answers

**Q: Why not use a single scraper for everything instead of RSS?**
A: RSS is significantly more efficient — it's a single HTTP request returning structured XML. Scraping requires launching a headless browser, waiting for JavaScript execution, and parsing unstructured HTML. RSS feeds also have clear schema contracts (title, link, description), while scraping is brittle to layout changes. I only use the scraper where RSS isn't available.

**Q: How do you handle a feed being temporarily down?**
A: Each feed is fetched independently using a bulkhead pattern — if Netflix's feed fails, it doesn't block Airbnb's. The fetcher catches exceptions per-feed, logs the error, and continues. Already-stored articles aren't affected. On the next run, the feed typically recovers.

**Q: How do you handle deduplication?**
A: Two layers. First, each article gets a deterministic ID via `MD5(url)` — same article always gets the same ID regardless of when it's fetched. Second, the SQLite insert uses `try/except IntegrityError` on the primary key — if the article already exists, it's silently skipped. This is idempotent — running the fetcher multiple times produces no duplicates.

**Q: What happens if a blog changes its URL structure?**
A: The web scraper uses regex patterns to filter article URLs. If LinkedIn changes their URL pattern, the regex would need updating. This is a known tradeoff of scraping. For RSS feeds, as long as the feed URL stays the same, URL structure changes in articles don't matter — the feed itself provides the canonical URLs.

**Q: How would you scale this to 1000 sources?**
A: Three changes: (1) Use async I/O (aiohttp) for parallel RSS fetching instead of sequential, (2) Use a task queue (Celery + Redis) for web scraping jobs since each Playwright instance is memory-heavy, (3) Add a circuit breaker per source so a single slow/failing feed doesn't consume resources.

---

## 4. Subsystem 2 — AI Analysis Pipeline

### What It Does
Sends each article to Claude AI to extract structured system design insights.

### Two-Stage Tagging

**Stage 1: Keyword Tagger** (`ai_tagger/topic_tagger.py`)
- Rule-based, zero-cost classification
- Maps keywords in title/summary to 15 predefined topics (Caching, Distributed-Systems, Load-Balancing, etc.)
- Runs at fetch time — every article gets immediate tags
- Falls back to "General" if no keywords match

**Stage 2: AI Tagger** (`ai_tagger/claude_tagger.py`)
- Calls Claude API (claude-haiku-4-5-20251001) for deep analysis
- Extracts: problem statement, solution approach, system design concepts, refined tags
- Returns structured JSON
- Runs after fetching as a separate step (decoupled)

### Design Decisions

| Decision | Reasoning |
|----------|-----------|
| Two-stage tagging | Keyword tagger is instant and free — gives immediate value. AI tagger adds depth but costs money and time. Separating them means the website is always useful, even if AI tagging fails. |
| Claude Haiku over Sonnet/Opus | 10x cheaper, fast enough for classification tasks. These are short articles, not complex reasoning tasks. |
| Lazy client initialization | Anthropic client is created on first use, not at import time. This means tests and the fetcher don't need an API key. |
| Structured JSON output | AI returns a fixed schema. If JSON parsing fails, the article keeps its keyword tags — graceful degradation. |

### Follow-Up Questions & Answers

**Q: Why not use embeddings + vector search instead of keyword matching?**
A: For 15 fixed categories and <200 articles, keyword matching is perfectly adequate — it's instant, free, and deterministic. Embeddings would add complexity (vector DB, embedding model costs) without meaningful accuracy improvement at this scale. If I had 1000+ categories or needed semantic similarity ("this article about 'sharding' is related to 'partitioning'"), then embeddings would be justified.

**Q: How do you handle AI API failures?**
A: Graceful degradation. If Claude returns invalid JSON or the API is down, the article keeps its keyword-based tags and gets a fallback message instead of AI analysis. The website still shows the article — it just doesn't have the AI insights section. I also handle empty summaries specifically — if an article has no summary (common with LinkedIn), I substitute a fallback prompt telling Claude to analyze based on the title alone.

**Q: What if the AI returns wrong tags?**
A: Since this is a personal learning tool, perfect accuracy isn't critical. The keyword tagger provides a reliable baseline. The AI tags are supplementary — they add concepts like "circuit-breaker" or "back-pressure" that keyword matching wouldn't catch. In a production system, I'd add a feedback loop where I could manually correct tags, and use those corrections to fine-tune the prompt.

**Q: Why not fine-tune a model instead of using prompting?**
A: Fine-tuning requires a training dataset of correctly-tagged articles, which I'd need to manually create first. Prompting with Claude gives 80% accuracy with zero training data. It's the right choice for a personal tool. For a production system with millions of articles, fine-tuning a smaller model (like BERT) would be more cost-effective.

---

## 5. Subsystem 3 — Storage Layer

### What It Does
Central persistence layer using SQLite. All reads and writes go through `storage.py`.

### Schema

```sql
CREATE TABLE articles (
    id           TEXT PRIMARY KEY,    -- MD5(url)
    url          TEXT UNIQUE,
    title        TEXT,
    summary      TEXT,
    company      TEXT,
    published_date TEXT,
    tags         TEXT,               -- JSON array: '["caching", "distributed-systems"]'
    week_label   TEXT,               -- "2026-W14"
    bookmarked   INTEGER DEFAULT 0,
    read_time    INTEGER,
    ai_problem   TEXT,               -- AI-extracted problem statement
    ai_approach  TEXT,               -- AI-extracted solution approach
    ai_concepts  TEXT                -- AI-extracted design concepts (JSON)
);

CREATE TABLE notes (
    id         TEXT PRIMARY KEY,
    title      TEXT,
    content    TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- Indexes for common query patterns
CREATE INDEX idx_week ON articles(week_label);
CREATE INDEX idx_company ON articles(company);
```

### Design Decisions

| Decision | Reasoning |
|----------|-----------|
| SQLite over PostgreSQL | Single-user app, <10K articles, deployed on a t3.micro. SQLite is zero-config, no daemon, the entire DB is one file. Perfect fit. |
| WAL mode | Write-Ahead Logging enables concurrent reads while writing. Without it, SQLite blocks all reads during a write. |
| Tags as JSON string | Simpler than a junction table for 15 tags. `LIKE '%"caching"%'` works for filtering. At scale, I'd normalize to a separate tags table. |
| Week label column | Denormalized — calculated from `published_date` at insert time. Avoids recalculating week groupings on every page load. |
| Migrated from JSON to SQLite | Started with a JSON file. As queries got complex (filter by tag + company + week), JSON required loading everything into memory. SQLite gives indexed queries. |

### Follow-Up Questions & Answers

**Q: Why SQLite instead of PostgreSQL or DynamoDB?**
A: SQLite is the right tool for this scale. The app has one writer (weekly cron job) and one reader (web server). SQLite handles this perfectly with WAL mode. PostgreSQL would add operational overhead (daemon process, connection pooling, backups) for zero benefit. DynamoDB would add cost and AWS lock-in. If I needed multi-server deployment or heavy concurrent writes, I'd switch to PostgreSQL.

**Q: What are the limitations of storing tags as a JSON string?**
A: Three main limitations: (1) Can't create an index on individual tags — `LIKE '%"caching"%'` does a full scan of the tags column, (2) Can't do relational queries like "find all tags" without scanning every row, (3) No referential integrity — nothing prevents typos in tag names. At my scale (<200 articles), this is fine. At 100K+ articles, I'd normalize to an `article_tags` junction table with a foreign key to a `tags` table.

**Q: How do you handle schema migrations?**
A: Currently, `_ensure_tables()` runs `CREATE TABLE IF NOT EXISTS` on every connection. For additive changes (new columns), I'd use `ALTER TABLE ADD COLUMN`. For destructive changes, I'd write a migration script. In a production system, I'd use a migration tool like Alembic (SQLAlchemy's migration framework) to version-control the schema.

**Q: What's your backup strategy?**
A: The SQLite database is a single file. The weekly cron could be extended to copy `techblog.db` to S3 before each run. Since all data can be regenerated (re-fetch + re-tag), backups are nice-to-have, not critical. User-generated data (bookmarks, notes) would be the only true loss.

**Q: Why not use an ORM like SQLAlchemy?**
A: For a small app with straightforward queries, raw SQL is more readable and has less magic. I know exactly what query is running. SQLAlchemy would add an abstraction layer that doesn't earn its complexity here. If the app grew to 20+ queries or needed to support multiple DB backends, I'd reconsider.

---

## 6. Subsystem 4 — Web Application

### What It Does
Flask website serving 5 pages with a custom "Botanical Morning" design system.

### Pages

| Page | Purpose | Key Feature |
|------|---------|-------------|
| **Home** | Current week's articles | Two-row filter bar (topics + source company), stats hero |
| **Archives** | All past weeks | Collapsible week accordions, same filter bar |
| **Bookmarks** | Saved articles | Fade-on-remove animation, persisted to SQLite |
| **Notes** | Personal study notes | Sidebar list + editor layout, full CRUD |
| **About** | System architecture | Pipeline visualization, tech stack display |

### Filter System
- **Topic filter:** 15 system design tags (Caching, Load-Balancing, etc.)
- **Company filter:** 7 source companies (Netflix, AWS, Meta, etc.)
- **Combined:** Both filters can be active simultaneously — dynamic WHERE clause construction
- **URL-based state:** Filters use query params (`?tag=caching&company=Netflix`), so filtered views are shareable/bookmarkable

### Design Decisions

| Decision | Reasoning |
|----------|-----------|
| Server-side rendering (Jinja2) | Content is mostly static, updated weekly. No need for React/Vue SPA overhead. Faster initial page load, better SEO, simpler deployment. |
| Custom CSS over Tailwind/Bootstrap | Full control over the design system. Consistent visual language via CSS custom properties (tokens). No unused CSS bloat. |
| Query params for filters | Stateless, bookmarkable, shareable. No JavaScript state management needed. Server handles all filtering logic. |
| Bookmark toggle via API | `POST /api/bookmark` toggles the bookmark in SQLite and returns JSON. JavaScript updates the UI optimistically. Keeps logic server-side. |

### Follow-Up Questions & Answers

**Q: Why Flask over Django or FastAPI?**
A: Flask is the right size for this project. Django includes an ORM, admin panel, and auth system I don't need — it would be overengineered. FastAPI is designed for async APIs, but I'm serving HTML templates, not a REST API. Flask with Jinja2 is purpose-built for this use case. If I needed an admin panel or user auth, Django would be the better choice.

**Q: How would you make this a single-page application?**
A: I'd keep Flask as a REST API backend (the `/api/bookmark` and `/api/notes` endpoints already exist), build a React frontend, and serve it as static files via Nginx. The filter logic would move client-side with React state + URL search params. But for a weekly-updated content site with <200 articles, SSR is actually faster and simpler.

**Q: How does the bookmark toggle work without a full page reload?**
A: It's a hybrid approach. Clicking the bookmark icon fires a `fetch()` POST to `/api/bookmark` with the article ID. The API toggles the `bookmarked` column in SQLite and returns `{status: "bookmarked"}` or `{status: "removed"}`. JavaScript receives the response and toggles the icon's CSS class. The button element is passed directly via `onclick="toggleBookmark(this, id)"` to avoid DOM lookup issues in async callbacks.

**Q: What's the Botanical Morning design system?**
A: It's a custom CSS design language I built using CSS custom properties (variables). It defines a consistent palette (earth tones — sage green, warm brown, cream), typography (Inter for UI, Lora for headlines), spacing scale, and component styles (pills, cards, filters). Every UI element references these tokens, so changing a color in one place updates the entire site. It's the same concept as a design system at a company like Airbnb (their design system is called "DLS").

---

## 7. Deployment Architecture

### Infrastructure

```
User → Port 80 → Nginx (reverse proxy)
                    ↓
              Unix Socket
                    ↓
              Gunicorn (2 workers, WSGI)
                    ↓
              Flask App
                    ↓
              SQLite (WAL mode)
```

### Components

**EC2 Instance:** t3.micro (Free Tier), Ubuntu 22.04
**Nginx:** Reverse proxy on port 80, forwards to Gunicorn via Unix socket
**Gunicorn:** 2 worker processes, manages Flask app lifecycle
**systemd:** Manages Gunicorn as a service (auto-restart on crash)
**Cron:** Weekly fetch + AI tag + email notification (Monday 8 AM)

### Why This Stack?

| Decision | Reasoning |
|----------|-----------|
| Nginx + Gunicorn (not Flask dev server) | Flask's built-in server is single-threaded and not production-ready. Gunicorn provides multiple worker processes. Nginx handles static files, SSL termination, and connection buffering. |
| Unix socket (not TCP port) | ~15% faster than TCP for same-machine communication. No port conflicts. More secure — no external access to Gunicorn directly. |
| 2 Gunicorn workers | Rule of thumb: `2 * CPU cores + 1`. t3.micro has 1 vCPU, so 2-3 workers. More workers = more memory on a 1GB machine. |
| systemd over Docker | Simpler for a single-app server. No container orchestration overhead. `systemctl restart techblog` is all I need. |

### Follow-Up Questions & Answers

**Q: Why not use Docker?**
A: For a single application on a single server, Docker adds a layer of indirection without clear benefit. I'd need to manage Docker installation, Dockerfile, image builds, and container networking. systemd gives me process management (auto-restart, logging) natively. If I had multiple services or needed reproducible environments across a team, Docker would be justified.

**Q: Why not use a managed service like AWS Elastic Beanstalk or Heroku?**
A: Two reasons: (1) Learning — I wanted to understand the full deployment stack (Nginx, Gunicorn, systemd, security groups) because these come up in system design interviews, (2) Cost — EC2 Free Tier is free for 12 months. Heroku's free tier was discontinued, and Elastic Beanstalk abstracts away the infrastructure knowledge I want to build.

**Q: How would you add HTTPS?**
A: Certbot (Let's Encrypt) with the Nginx plugin. It automatically obtains a free SSL certificate, configures Nginx to serve on port 443, and sets up auto-renewal via cron. The Nginx config would add a `server` block that redirects port 80 to 443. Total setup: ~5 minutes.

**Q: What happens if the EC2 instance goes down?**
A: The systemd service has `Restart=always`, so if Gunicorn crashes, it auto-restarts in 3 seconds. If the entire EC2 instance terminates, I'd need to launch a new one and run the setup script. The SQLite database would be lost unless backed up. For true high availability, I'd need: (1) RDS or S3-backed database, (2) Auto Scaling Group with min 1 instance, (3) Application Load Balancer for health checks.

**Q: How would you scale this to handle 10,000 users?**
A: Progressive scaling path:
1. **Vertical:** Upgrade from t3.micro to t3.medium (more CPU/RAM) — handles ~100 concurrent users
2. **Caching:** Add Redis to cache homepage queries (articles change weekly, not per-request)
3. **CDN:** Put CloudFront in front of Nginx for static assets and page caching
4. **Horizontal:** Move SQLite to RDS PostgreSQL, put Flask behind an ALB with 2-3 EC2 instances in an Auto Scaling Group
5. **Serverless:** At extreme scale, move to Lambda + API Gateway + DynamoDB — pay per request, auto-scales to zero

---

## 8. CI/CD Pipeline

### Pipeline Flow

```
Push to main
     ↓
GitHub Actions: Run Tests (92 pytest cases)
     ↓ (pass)
GitHub Actions: SSH into EC2
     ↓
git pull → pip install → systemctl restart
     ↓
Live in production (~60 seconds total)
```

### Workflow Configuration

```yaml
on:
  push:
    branches: [main]       # Deploy on push to main
  pull_request:
    branches: [main]       # Test-only on PRs (no deploy)

jobs:
  test:     # Stage 1: Run pytest on GitHub-hosted runner
  deploy:   # Stage 2: SSH to EC2 (only if tests pass + push to main)
```

### Secrets Management
- `EC2_HOST` — Instance IP (stored in GitHub Secrets)
- `EC2_USER` — SSH username
- `EC2_SSH_KEY` — Private key (never committed to repo)

### Design Decisions

| Decision | Reasoning |
|----------|-----------|
| GitHub Actions over Jenkins | Zero infrastructure to manage. Jenkins requires its own server. GitHub Actions is free for public repos and tightly integrated with GitHub. |
| SSH deploy over Docker push | No container registry needed. `git pull + restart` is the simplest deployment model for a single server. |
| Tests gate deployment | Deploy job has `needs: test` and `if: github.ref == 'refs/heads/main'`. PRs only run tests. This prevents broken code from reaching production. |
| pip install on every deploy | Ensures new dependencies are always installed. `--quiet` flag keeps the output clean. Takes ~5 seconds — acceptable for weekly deployments. |

### Follow-Up Questions & Answers

**Q: What if the deploy step fails mid-way?**
A: The deploy script is sequential: `git pull → pip install → restart`. If `git pull` fails, nothing changes. If `pip install` fails, the old code is still running (Gunicorn hasn't restarted). If `systemctl restart` fails, systemd auto-restarts from the previous working state. The worst case is a bad code deploy — the new code is pulled but crashes on startup. Gunicorn's `Restart=always` would cause a restart loop. I'd SSH in manually and `git revert`.

**Q: How would you implement zero-downtime deployment?**
A: Three options: (1) **Gunicorn graceful reload:** `kill -HUP <pid>` — workers finish current requests before restarting. (2) **Blue-green deployment:** Run two Gunicorn instances, switch Nginx upstream after health check. (3) **Rolling deploy with ALB:** If using multiple EC2 instances, deploy to one at a time while the ALB routes traffic to healthy instances.

**Q: How would you add rollback capability?**
A: Tag each deployment with the git commit SHA. Store the last 5 deployed SHAs. A rollback script would: `git checkout <previous-sha> → restart`. More robustly, I'd deploy from built artifacts (Docker images tagged with SHA) rather than `git pull`, so rollback is just pointing to a previous image.

**Q: Why not use AWS CodeDeploy or CodePipeline?**
A: They're designed for large teams with complex deployment needs (approval gates, deployment groups, rollback policies). For a single-server personal project, GitHub Actions + SSH is simpler, faster to set up, and has zero AWS cost. If I had 10 EC2 instances, CodeDeploy's rolling deployment feature would be valuable.

---

## 9. Email Notifications (AWS SES)

### What It Does
Sends a weekly HTML email summarizing new articles fetched that week.

### Architecture

```
Cron (Monday 8 AM)
     ↓
weekly_update.sh: fetch → tag → check count
     ↓ (if new articles > 0)
notify.py: Query SQLite → Build HTML → Send via SES
     ↓
AWS SES → teju.aswini21@gmail.com
```

### How It Works
1. `weekly_update.sh` captures the count of newly fetched articles
2. If count > 0, it calls `notify.py` with the count
3. `notify.py` queries SQLite for articles from the last 7 days
4. Builds a styled HTML email matching the Botanical Morning theme
5. Sends via `boto3` SES client using IAM role authentication (no hardcoded keys)

### Design Decisions

| Decision | Reasoning |
|----------|-----------|
| SES over SendGrid/Mailgun | Already on AWS. SES is $0.10 per 1,000 emails. No additional vendor. IAM role authentication means no API keys to manage. |
| IAM role over access keys | EC2 instance role provides temporary credentials automatically. No keys stored on disk or in environment variables. More secure, auto-rotated. |
| Conditional send | Only sends email if new articles were actually fetched. No "0 new articles this week" spam. |
| HTML + plain text | HTML for rich formatting, plain text fallback for email clients that don't render HTML. |

### Follow-Up Questions & Answers

**Q: How do you prevent emails from going to spam?**
A: Three steps: (1) Verify the sender domain in SES (SPF/DKIM records), (2) Move out of SES sandbox mode (requires AWS approval — production access), (3) Warm up the sending IP gradually. Currently in sandbox mode, which means emails can only go to verified addresses and may hit spam filters.

**Q: How would you add subscriber management?**
A: Add a `subscribers` table in SQLite with email and preferences (which companies/topics they want). The notification script would query per-subscriber preferences and send personalized emails. For unsubscribe, include a tokenized unsubscribe link in each email that hits a Flask endpoint to remove the subscriber.

---

## 10. Testing Strategy

### Test Suite: 92 Tests

| Module | Tests | What's Covered |
|--------|-------|----------------|
| `test_storage.py` | 17 | CRUD operations, deduplication, week label calculation, row parsing |
| `test_rss_fetcher.py` | 17 | HTML stripping, entry normalization, feed parsing (mocked feedparser) |
| `test_web_app.py` | 24 | All routes, bookmark API, notes CRUD, helper functions |
| `test_topic_tagger.py` | 10 | Single/multi tag matching, case insensitivity, edge cases |
| `test_claude_tagger.py` | 7 | AI analysis with mocked Anthropic client, error handling |
| `test_web_scraper.py` | 5 | Article building, deterministic IDs, scraper error handling |

### Testing Patterns Used

- **Fixtures:** `conftest.py` provides reusable `sample_article`, `tmp_db` (isolated SQLite), `flask_client`
- **Monkeypatching:** Override `DB_FILE` path to use temp database per test
- **Mocking:** External APIs (Claude, feedparser, Playwright) are mocked — tests never make real network calls
- **Isolation:** Each test gets its own temp database, no shared state between tests

### Follow-Up Questions & Answers

**Q: Why mock external APIs instead of using integration tests?**
A: Unit tests must be fast, deterministic, and free. Calling Claude API in tests would cost money, be slow (~1s per call), and could fail due to network issues — making CI flaky. I mock the API to test my code's logic (prompt construction, response parsing, error handling). Integration tests against real APIs would run separately, manually, not in CI.

**Q: How do you test the database layer without a real database?**
A: I do use a real SQLite database — but a temporary one. The `tmp_db` fixture creates a fresh SQLite file in `/tmp`, monkeypatches `storage.DB_FILE` to point to it, and deletes it after the test. Each test starts with an empty, isolated database. This is actually better than mocking — it tests real SQL queries against real SQLite.

**Q: What's not tested?**
A: End-to-end browser tests (Selenium/Playwright testing the actual UI), the SES email sending (would need localstack or real SES), and the deployment scripts. In a production system, I'd add: (1) E2E tests with Playwright, (2) Load tests with locust, (3) Contract tests for the AI tagger's JSON schema.

---

## 11. Key Design Patterns & Principles

| Pattern | Where Used | Why |
|---------|-----------|-----|
| **Adapter Pattern** | RSS fetcher + Web scraper return identical `{id, title, url, ...}` schema | Swap data sources without changing downstream code |
| **Bulkhead Pattern** | Each feed is fetched independently; one failure doesn't block others | Fault isolation — Netflix being down doesn't prevent Airbnb from loading |
| **Graceful Degradation** | AI tagger failure falls back to keyword tags | System remains functional at reduced quality |
| **Idempotency** | Re-running fetcher produces no duplicates (MD5 ID + IntegrityError catch) | Safe retries, cron-friendly |
| **Denormalization** | `week_label` column computed at insert time | Avoids repeated date calculations on every read |
| **Normalization at Boundary** | HTML stripped, dates parsed, schemas unified at ingestion | Downstream systems work with clean, consistent data |
| **Single Responsibility** | `storage.py` is the only file that touches SQLite | One place to change if database logic changes |

---

## 12. What I'd Do Differently / Future Improvements

1. **Use PostgreSQL from the start** — SQLite's JSON-as-string approach for tags doesn't scale. PostgreSQL has native JSONB with indexing.
2. **Add a message queue** — Instead of a bash script chaining fetch → tag → notify, use Celery + Redis for async task processing with retry logic.
3. **Add observability** — Structured logging (JSON logs), health check endpoint (`/health`), and basic metrics (articles fetched per run, API latency).
4. **Container-first deployment** — Dockerfile + docker-compose for local dev parity with production. GitHub Actions would build + push image, EC2 would pull + run.
5. **Add full-text search** — SQLite FTS5 extension for searching across article titles and summaries.

---

## 13. Production Scale Design

> "How would you take this system to production at scale?"

### Production Architecture

```
CloudFront + WAF
      ↓
API Gateway (rate limit, auth, request validation)
      ↓
Application Load Balancer
   ↓              ↓
Web EC2        Web EC2     ← Auto Scaling Group, stateless
      ↓
   RDS PostgreSQL (Multi-AZ)       ElastiCache Redis
   (articles, users, bookmarks,    (sessions, rate limits,
    notes, metadata)                AI cache)

EventBridge Scheduler (cron)
      ↓
   Lambda/ECS: Crawler ──→ SQS ──→ AI Tagger
                                  ↓ (on failure)
                                 DLQ
      ↓
   RDS PostgreSQL
   S3 (raw article content)
      ↓
   SES (email notifications)
```

---

### What Changes vs. Current Design

| Component | Current | Production |
|-----------|---------|------------|
| Web server | Single EC2 | Auto Scaling Group behind ALB |
| Database | SQLite | RDS PostgreSQL Multi-AZ + Read Replica |
| Cache | None | ElastiCache Redis |
| Crawler | Cron on EC2 | Lambda triggered by EventBridge |
| AI Tagger | Sequential on EC2 | ECS worker consuming SQS queue |
| Secrets | `.env` file | AWS Secrets Manager (auto-rotated) |
| Monitoring | None | CloudWatch + Sentry + X-Ray |
| Auth | None | AWS Cognito (Google/GitHub OAuth) |

---

### Per-User Customization (Auth)

- **Cognito** handles OAuth (Google/GitHub sign-in), JWT tokens, user pools
- Add `user_id` FK to `bookmarks` and `notes` tables — articles stay shared
- Web server is already stateless (no session on server) — just validate JWT on each request
- Rate limits move to API Gateway per `user_id` instead of per IP

---

### Service Separation

**Why split Crawler, AI Tagger, and Web into separate services?**
- **Independent scaling** — AI tagging is slow (Claude API) and doesn't need to scale with web traffic
- **Fault isolation** — Claude API being down doesn't affect the website
- **Independent deployment** — deploy new AI prompt without touching web server

**SQS between Crawler and AI Tagger:**
- Crawler drops article IDs into SQS after fetching
- AI Tagger workers pull from SQS and process one at a time
- If Claude is rate-limited, messages wait in queue — no data loss
- If a message fails 3 times → moves to **Dead Letter Queue (DLQ)** for inspection

---

### Data Layer Decisions

**PostgreSQL over SQLite:**
- Multi-writer safe (multiple EC2 instances writing simultaneously)
- Native JSONB with indexing (fix the `tags LIKE '%"caching"%'` full scan)
- Row-level locking, connection pooling via **RDS Proxy**

**Why RDS Proxy?**
Each Lambda invocation opens a new DB connection. With 100 concurrent Lambdas, you hit PostgreSQL's connection limit (~100 by default). RDS Proxy pools connections — Lambdas connect to the proxy, proxy maintains a small pool to RDS.

**Redis for:**
- Homepage query cache (articles change weekly — cache for 1 hour)
- Rate limit counters (atomic increment with TTL)
- Session tokens (if not using Cognito)
- Claude API response cache (same article URL → same analysis, skip re-tagging)

**S3 for raw content:**
- Store full article HTML/text in S3, keep S3 key in PostgreSQL
- Cheaper than storing large text blobs in DB at scale
- Enables re-processing (re-run AI tagger on all historical articles)

**Notes stay in PostgreSQL** (not MongoDB):
- Notes are flat rows: `{user_id, article_id, content, timestamps}`
- No nested document structure that would justify MongoDB
- MongoDB adds operational overhead with no real benefit here

---

### Scheduler Design

**EventBridge for weekly cron** (simple, managed):
```
EventBridge rule: cron(0 8 ? * MON *)
  → triggers Lambda: run_crawler
  → Lambda writes new article IDs to SQS
  → AI Tagger ECS workers consume SQS
```

**DynamoDB scheduler table** (for per-user scheduling):
Use this when you need user-level scheduling (e.g., "send digest at user's preferred timezone"):
```
PK: time_bucket (e.g., "2026-04-14T08:00")   ← keeps writes distributed
SK: user_id
Attributes: preferences, last_sent, status
```
Time bucket as PK avoids hot partition — all 8AM sends don't land on the same partition key.

---

### Security

- **VPC**: EC2 in public subnet, RDS in private subnet — DB never publicly accessible
- **Secrets Manager**: DB passwords, API keys stored and auto-rotated — no `.env` files on servers
- **RDS encryption at rest**: one checkbox, always enable
- **WAF**: blocks SQL injection, XSS, bad bots at the edge before hitting servers
- **IAM least privilege**: each service has its own role with only the permissions it needs
- **Input sanitization**: parameterized queries (already done) + output escaping for XSS

---

### Observability

**The three pillars of production observability:**

**Logs** — CloudWatch Logs (or ELK stack)
- Structured JSON logs: `{timestamp, level, route, user_id, latency_ms, status}`
- Every request, every error, every AI tagging result logged

**Metrics** — CloudWatch Alarms → SNS → email/Slack
- Alert when: error rate > 1%, CPU > 80%, SQS queue depth > 100, RDS connections > 80%

**Traces** — AWS X-Ray
- Traces a single request across Web → SQS → AI Tagger
- Shows exactly where latency is coming from in the pipeline

**Error tracking** — Sentry
- Groups exceptions by type, shows stack traces, alerts on new errors
- Catches the "Claude returned invalid JSON" errors that currently go unnoticed

---

### Resilience Patterns

**Circuit breaker on Claude API:**
- After 5 consecutive failures, stop calling Claude for 60 seconds (fail fast)
- Articles still get keyword tags — AI tags fill in on next successful run
- Prevents thundering herd when Claude recovers

**Retry with exponential backoff:**
- RSS fetch failure: retry after 1s, 2s, 4s — then give up and log
- Claude API 429 (rate limited): back off and retry, don't flood

**RDS Multi-AZ:**
- Standby replica in a different AZ
- Automatic failover in ~60 seconds if primary goes down
- No data loss (synchronous replication)

**RDS Read Replica:**
- Homepage article queries → read replica
- Only writes (bookmarks, notes) → primary
- Keeps read traffic off the primary as you scale

---

### GDPR (Required for .uk domain)

- **Cookie consent banner** — legally required for EU/UK users
- **Right to deletion** — `DELETE /api/user` removes all user data (notes, bookmarks, account)
- **Data retention policy** — how long do you keep articles, logs, user data?
- **Privacy policy page** — what you collect, why, how long
- **Anthropic as data processor** — article content sent to Claude API falls under their DPA

---

### Cost Controls

- **Billing alerts** — AWS Budget alarm at $10/month
- **Reserved instances** — 1-year reserved EC2/RDS saves ~40% vs on-demand
- **Claude API spend cap** — set monthly limit in Anthropic console
- **S3 lifecycle policies** — move old article content to Glacier after 1 year
- **CloudFront caching** — cache homepage at CDN layer, reduces EC2 load dramatically

---

### Key Interviewer Follow-Ups & Answers

**"What happens if the AI Tagger is down?"**
> Messages stay in SQS — no data loss. After 3 failures, the message moves to a Dead Letter Queue for manual inspection. Articles are still served with keyword tags in the meantime. When the tagger recovers, it picks up where it left off.

**"How do you handle DB connection exhaustion with 100 Lambda instances?"**
> RDS Proxy. Each Lambda connects to the proxy, which maintains a small persistent pool to RDS. Lambda thinks it has a direct connection; RDS sees a stable set of ~10 connections regardless of how many Lambdas are running.

**"How do you deploy a schema change with zero downtime?"**
> Backward-compatible migrations with Alembic. Step 1: add new column (nullable, no default) — old code still works. Step 2: deploy new code that writes to the new column. Step 3: backfill existing rows. Step 4: add NOT NULL constraint. Never rename or drop a column in the same deploy as the code change that stops using it.

**"How do you know when something is broken in production?"**
> Three layers: CloudWatch alarm fires when error rate > 1% → SNS notification. Sentry catches and groups exceptions with stack traces. X-Ray shows if latency is spiking in a specific service. Without all three, you're flying blind.

**"Why not MongoDB for notes?"**
> Notes are flat rows: user_id, article_id, content, timestamps. There's no nested document structure that justifies a document store. Adding MongoDB means another managed service, another connection pool, another thing to back up, another failure mode — with zero benefit over PostgreSQL for this data shape. MongoDB is right when you have genuinely variable, nested document structures like Notion pages or product catalogs.

**"How would you handle a viral traffic spike?"**
> CloudFront serves cached pages — most traffic never hits EC2. For requests that do reach EC2, the Auto Scaling Group adds instances when CPU > 70%. The ALB health checks route around unhealthy instances. RDS Read Replica handles the read surge. The bottleneck would likely be the write path (bookmarks) — Redis rate limiting prevents abuse, and RDS can handle thousands of writes per second.

---

## 14. Common Interviewer Challenges

**"This seems over-engineered for a personal tool."**
> That's intentional. The goal was to practice production engineering patterns at a manageable scale. Every decision (WAL mode, Nginx reverse proxy, CI/CD) maps to a real-world concept that comes up in system design interviews. Building it myself gave me hands-on understanding that reading alone wouldn't provide.

**"Why not just use a note-taking app?"**
> The value isn't just reading articles — it's the automated pipeline. Every Monday, fresh articles are fetched, AI-analyzed, and delivered to my inbox. The system design concepts are extracted automatically. I spend time learning, not curating. Plus, building the system itself taught me more about distributed systems than reading about them.

**"What was the hardest bug you encountered?"**
> The ISO week date calculation. Python has two week numbering systems: `%W` (Sunday-start, Jan 1 = week 0) and `%V` (ISO Monday-start, Jan 4 = week 1). I was using `%Y-W%W-%w` which showed "Apr 06-12" for the current week when it should have been "Mar 30 - Apr 05". The fix was switching to `%G-W%V-%u` (ISO year + ISO week + ISO weekday). It's a subtle bug that only manifests at year boundaries or specific week transitions — exactly the kind of thing you'd catch in production, not in testing.

**"Walk me through a request lifecycle."**
> User visits `/?tag=caching&company=Netflix`. Nginx receives the request on port 80, forwards it to Gunicorn via Unix socket. Gunicorn dispatches to one of 2 Flask workers. Flask's `home()` route reads `tag` and `company` from query params, builds a dynamic SQL WHERE clause (`week_label = ? AND tags LIKE ? AND company = ?`), queries SQLite, groups results by week, and renders the Jinja2 template. The HTML response flows back through Gunicorn → Nginx → user. Total latency: ~20ms.
