# Tech Blog Digest — Requirements & Plan

## What Is This?

A personal website that aggregates engineering blog posts from big tech companies (Netflix, LinkedIn, Uber, etc.), organizes them by week and system design topic, and provides a space to write study notes. Built for interview preparation and continuous learning.

## Companion Repo

The data pipeline (RSS fetcher, AI tagger, PPTX builder) lives in:
`/Users/tejaswinikb/RiderProjects/Tech-blog-system`

This repo is the **website + deployment layer** that reads from the same database.

---

## Core Requirements

| # | Feature | Description |
|---|---------|-------------|
| 1 | Weekly article view | Homepage shows articles grouped by week (e.g., "March 30 – April 5") |
| 2 | Tag-filtered table | Articles in tabular format, filtered by tag, ~5 per tag, company name shown |
| 3 | Homepage = latest week | Landing page always shows the current/latest week's articles |
| 4 | Archives page | Browse previous weeks' articles |
| 5 | Notes section | Web editor to write & save learnings per article (stored in SQLite) |
| 6 | Weekly scheduler | Cron job every Sunday night: fetch → AI tag → populate |
| 7 | Deployment | AWS EC2 Free Tier (t2.micro or t4g.micro) |
| 8 | Auto-populate | New articles appear on homepage after scheduler runs |
| 9 | About page | Static page with personal details |
| 10 | robots.txt compliance | Fetcher/scraper respects robots.txt of target blogs |

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Web framework | Flask | Python (consistent with pipeline), lightweight |
| Database | SQLite | Single file, zero setup, single-user site |
| Data migration | articles.json → SQLite | Single source of truth, cleaner queries |
| Notes storage | SQLite (same DB) | Web editor writes directly |
| Hosting | AWS EC2 Free Tier | Free 12 months, full control, runs scheduler |
| Reverse proxy | Nginx | Serves static files, HTTPS termination |
| SSL | Let's Encrypt (certbot) | Free, auto-renewing |
| Scheduler | Cron on EC2 | Sunday 11 PM: fetch + AI tag + populate |

---

## Pages

### 1. Homepage
- Header: site title + nav (Home, Archives, Notes, About)
- Current week's date range displayed prominently
- Articles grouped by tag in collapsible sections
- Each section: table with columns — Title (link), Company, Problem summary
- Up to 5 articles per tag

### 2. Archives
- List of previous weeks (cards or rows)
- Click a week → same table format as homepage
- Newest first

### 3. Notes
- Left sidebar: list of articles marked as read
- Right: text editor for writing learnings
- Shows article title, company, link at top
- Save button → persists to SQLite
- Previously saved notes visible on click

### 4. About
- Photo placeholder, name, bio
- "What is this site?" section
- Social links (LinkedIn, GitHub, Twitter placeholders)

---

## Design

- Clean, minimal, professional
- Dark navy header (#065A82), white/light gray body (#F5F7FA)
- Mint teal accents (#02C39A)
- Sans-serif fonts (Inter or system)
- Responsive (mobile-friendly)
- No flashy animations — readability and information density

---

## Database Schema

### articles table
```sql
CREATE TABLE articles (
    id          TEXT PRIMARY KEY,    -- 12-char MD5 hash of URL
    url         TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT DEFAULT '',
    company     TEXT NOT NULL,
    blog_name   TEXT NOT NULL,
    tags        TEXT NOT NULL,       -- JSON array: ["caching", "distributed-systems"]
    tags_hint   TEXT DEFAULT '[]',   -- JSON array from blog config
    published   TEXT DEFAULT '',     -- ISO 8601
    fetched_at  TEXT NOT NULL,       -- ISO 8601
    status      TEXT DEFAULT 'new',  -- new | in-progress | done
    ai_problem  TEXT,                -- from ai_summary.problem
    ai_solution TEXT,                -- from ai_summary.solution
    ai_concepts TEXT,                -- JSON array of concepts
    ai_tagged_at TEXT,               -- ISO 8601
    week_label  TEXT                 -- e.g., "2026-W14" for grouping
);
```

### notes table
```sql
CREATE TABLE notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL REFERENCES articles(id),
    content     TEXT NOT NULL,       -- markdown or plain text
    created_at  TEXT NOT NULL,       -- ISO 8601
    updated_at  TEXT NOT NULL        -- ISO 8601
);
```

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                  AWS EC2 (t2.micro)                   │
│                                                       │
│  ┌──────────────┐    ┌───────────────┐               │
│  │  Flask App    │    │  SQLite DB     │               │
│  │  (gunicorn)   │◄──►│  articles      │               │
│  │               │    │  notes         │               │
│  └──────┬────────┘    └───────┬───────┘               │
│         │                     ▲                       │
│    Nginx│(reverse proxy)      │                       │
│    :80/:443              ┌────┴────────┐              │
│         │                │  Cron Job    │              │
│         ▼                │  (Sun 11PM)  │              │
│    Public internet       │  fetch→tag   │              │
│                          └─────────────┘              │
└──────────────────────────────────────────────────────┘
```

---

## Pricing

| Item | Monthly Cost |
|------|-------------|
| EC2 t2.micro | $0 (free 12 months) |
| EBS 8GB | $0 (free tier) |
| Elastic IP | $0 (while attached) |
| SSL (Let's Encrypt) | $0 |
| Claude API (AI tagger) | ~$0.15–0.40 |
| Domain (optional) | ~$1/mo |
| **Total** | **~$0.15–0.40/month** |

After 12 months: switch to t4g.micro (always-free ARM tier) → hosting stays $0.

---

## Implementation Phases

### Phase 1: Database + Flask App (local)
- [ ] SQLite schema + migration script (articles.json → SQLite)
- [ ] Flask app skeleton (routes, templates, static)
- [ ] Homepage with weekly grouping + tag filter
- [ ] Archives page
- [ ] About page

### Phase 2: Notes + Scheduler
- [ ] Notes CRUD (web editor + SQLite persistence)
- [ ] robots.txt compliance in fetcher
- [ ] Weekly pipeline script (fetch → tag → populate)
- [ ] Test scheduler locally

### Phase 3: Deploy to EC2
- [ ] Provision EC2 + security group
- [ ] Install Python, Nginx, certbot, gunicorn
- [ ] Deploy Flask app + SQLite
- [ ] Set up cron job
- [ ] (Optional) Domain + SSL

---

## v0.dev Prompt

Paste the following into v0.dev to generate a UI prototype:

```
Build a personal tech blog aggregator website with these pages:

1. HOMEPAGE
- Header with site title "Tech Blog Digest" and navigation (Home, Archives, Notes, About)
- Shows the current week's date range prominently (e.g., "Week: March 30 – April 5, 2026")
- Articles displayed in a clean table grouped by tags
- Each tag section shows up to 5 articles with columns: Article Title (link), Company (badge), Problem summary
- Tag sections are collapsible or shown as tabs/pills

2. ARCHIVES PAGE
- List of previous weeks as cards or rows
- Click a week to see that week's articles

3. NOTES PAGE
- Left sidebar: list of articles I've read
- Right side: text editor for writing learnings
- Save button, previously saved notes visible

4. ABOUT PAGE
- Personal profile section with photo, name, bio
- "What is this site?" explanation

DESIGN:
- Dark navy header (#065A82), white/light gray body (#F5F7FA), teal accents (#02C39A)
- Sans-serif fonts (Inter or similar)
- Responsive, clean, minimal
```
