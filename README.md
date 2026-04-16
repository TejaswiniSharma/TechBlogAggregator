# Distributed Readings — Tech Blog Aggregator

A personal engineering learning system that aggregates articles from 12+ big tech
engineering blogs, analyzes them with AI, and serves a clean website for study and
interview prep.

**Live:** https://distributedreadings.uk

---

## What It Does

```
RSS Feeds (Netflix, Uber, Airbnb, ...)
    → Fetcher (feedparser + Playwright)
    → AI Tagger (Claude API)
    → Flask Website (Botanical Morning theme)
```

1. **Fetches** articles from 12 engineering blogs via RSS (+ Playwright for LinkedIn)
2. **Analyzes** each article with Claude AI — extracts core problem, solution, system design concepts
3. **Serves** a website with weekly article feeds, tag filtering, bookmarks, and notes

---

## Quick Start (Local)

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Fetch articles from all blogs
python3 run_fetch.py

# 3. AI-tag articles (needs API key)
export ANTHROPIC_API_KEY="sk-ant-..."
python3 run_ai_tag.py

# 4. Start the website
python3 web/app.py
# Visit http://localhost:5001
```

---

## File Map

```
TechBlogAggregator/
├── run_fetch.py              CLI — fetch articles from all blogs
├── run_ai_tag.py             CLI — send articles to Claude for analysis
├── requirements.txt          Python dependencies
├── config/
│   └── blogs.py              12 blog configs (RSS URLs, company metadata)
├── fetcher/
│   ├── rss_fetcher.py        RSS parser + normalizer
│   ├── web_scraper.py        Playwright scraper (LinkedIn)
│   ├── topic_tagger.py       Keyword-based topic tagger
│   └── storage.py            SQLite persistence layer
├── ai_tagger/
│   └── claude_tagger.py      Claude API integration — structured analysis
├── web/
│   ├── app.py                Flask app (routes + API endpoints)
│   └── templates/
│       ├── base.html          Botanical Morning design system + navbar
│       ├── home.html          Homepage (hero, stats, filters, card grid)
│       ├── archives.html      All weeks in collapsible accordions
│       ├── bookmarks.html     Saved articles
│       ├── notes.html         Personal notes editor
│       └── about.html         About page
├── scripts/
│   └── weekly_update.sh      Cron script — fetch + tag weekly
├── deploy/
│   ├── setup.sh              One-command EC2 deployment
│   ├── techblog.service      Gunicorn systemd service
│   └── nginx-techblog        Nginx reverse proxy config
└── data/
    └── techblogs.db           SQLite database (generated on first run)
```

---

## Deploy to AWS EC2

On a fresh Ubuntu 22.04 `t2.micro` (Free Tier):

```bash
curl -s https://raw.githubusercontent.com/TejaswiniSharma/TechBlogAggregator/main/deploy/setup.sh | bash
```

This installs everything: Python, Nginx, Gunicorn, clones the repo, and starts the server.

See `deploy/setup.sh` for the full breakdown.

---

## Website Features

| Page | What it does |
|------|-------------|
| **Home** | Greeting, weekly stats, tag filter pills, 2-column article cards with bookmark toggle |
| **Archives** | All weeks in collapsible accordions, same filtering |
| **Bookmarks** | Saved articles with live badge count |
| **Notes** | Personal notes editor linked to articles |
| **About** | System overview, pipeline steps, tech stack |

Design: **Botanical Morning** — a warm, natural theme with leaf greens, blossom pinks, and cream backgrounds. Lora serif headings, Inter sans body text.

---

## Architecture

| Component | Technology | Why |
|-----------|-----------|-----|
| RSS Fetcher | feedparser | Handles RSS 0.9, 2.0, Atom — normalizes all formats |
| LinkedIn Scraper | Playwright | LinkedIn has no RSS — JS-rendered SPA needs headless browser |
| AI Tagger | Claude Haiku | Fast + cheap for batch analysis — extracts problem/solution/concepts |
| Storage | SQLite | Single-file DB, no server needed, supports queries and indexes |
| Web Framework | Flask | Lightweight, perfect for personal tools |
| Production Server | Gunicorn + Nginx | Gunicorn handles Python, Nginx handles HTTP |
| Hosting | AWS EC2 Free Tier | t2/t3.micro, 750 hours/month free |

---

## Interview Topics Covered

| Topic | Key Concepts |
|-------|-------------|
| caching | Redis, LRU, cache invalidation, write-through/back |
| rate-limiting | Token bucket, leaky bucket, sliding window |
| distributed-systems | Consensus, CAP theorem, replication, quorum |
| databases | Sharding, indexing, ACID, B-tree, LSM |
| messaging-queues | Kafka, pub/sub, consumer groups, dead letter |
| microservices | Service mesh, gRPC, circuit breaker, k8s |
| load-balancing | Round robin, health checks, Layer 4 vs 7 |
| observability | Metrics, tracing, SLO/SLA, p99 latency |
| ml-systems | Feature stores, model serving, embeddings |
| search | Inverted index, vector search, relevance ranking |
| real-time-systems | Streaming, WebSocket, CDC, Flink |
| storage-systems | Object storage, S3, erasure coding, data lakes |
| api-design | REST, GraphQL, idempotency, versioning |
| security | OAuth, JWT, zero trust, TLS |
| chaos-engineering | Fault injection, chaos monkey, bulkheads |

---

## Engineering Blogs Tracked

Netflix · Airbnb · Uber · LinkedIn · Stripe · Meta · Cloudflare · AWS · Dropbox · Spotify · DoorDash · Shopify

---

Built by Tejaswini for system design interview prep.
