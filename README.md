# Tech Blog Learning System
## Subsystem 1: Blog Fetcher

A personal engineering learning system. Fetches articles from big tech engineering blogs,
tags them by system design topic, and stores them for on-demand study and PPTX generation.

---

## Quick Start

```bash
# 1. Install dependency
pip install -r requirements.txt

# 2. Fetch all blogs
python run_fetch.py

# 3. Browse by interview topic
python run_fetch.py --filter-topic caching
python run_fetch.py --filter-topic microservices
python run_fetch.py --filter-topic distributed-systems

# 4. Browse by company
python run_fetch.py --filter-topic caching --company Netflix

# 5. See all available topics
python run_fetch.py --list-topics
```

---

## File Map

```
tech-blog-system/
├── run_fetch.py              Entry point (CLI)
├── requirements.txt          One dependency: feedparser
├── config/
│   └── blogs.py              RSS feed URLs + metadata for each blog
├── fetcher/
│   ├── rss_fetcher.py        Core: fetches + normalizes RSS entries
│   ├── topic_tagger.py       Tags articles with interview topics (keyword matching)
│   └── storage.py            Read/write articles.json (shared data store)
└── data/
    └── articles.json         Generated on first run — your article library
```

---

## Architecture Decisions & Why

### Why RSS over scraping?
RSS is a *published contract*. When a blog redesigns, the RSS feed stays stable.
Web scraping breaks every time HTML structure changes (which is frequent).
If a company doesn't publish RSS (some don't), scraping becomes the fallback.

### Why JSON storage, not a database?
For learning: JSON is transparent. `cat data/articles.json` tells you exactly what's stored.
For production: SQLite when you need queries, Postgres when you need concurrent writes.
Don't add complexity until you have a problem that complexity solves.

### Why keyword tagging instead of AI tagging?
This runs on every article, potentially hundreds per day.
A Claude API call costs money and milliseconds. Keywords cost nothing.
Progressive enhancement: instrument keyword tagging first, measure accuracy,
then upgrade to AI tagging (Subsystem 2) where it's actually needed.

### Why sequential fetch instead of async?
Start simple. Race conditions in async code are hard to debug.
When you have performance data showing the bottleneck is network I/O,
switch to `asyncio + aiohttp`. The `fetch_blog()` interface stays identical.

### Why deduplicate by URL?
RSS feeds republish articles on edits. Without deduplication, you get 30 copies
of the same post. URL is the natural canonical ID for web content.
In production: a bloom filter handles this at LinkedIn/Netflix scale.

---

## Interview Topics Available

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

## What's Next

| Subsystem | What it does | Key technology |
|-----------|-------------|---------------|
| **2 - AI Tagger** | Sends articles to Claude API, extracts: core problem, how they solved it, interview concepts | Anthropic API |
| **3 - PPTX Builder** | Auto-generates study slide for each article | python-pptx |
| **4 - Tracker** | Spaced repetition queue, mark articles done | JSON + date math |

---

## Real-World Connections

Every design decision in this system maps to a real engineering pattern:

- **Normalize at ingestion** → How Stripe handles multi-provider webhooks
- **Shared data store** → How Netflix's microservices share state via Cassandra
- **Bulkhead pattern** → Why one bad RSS feed doesn't kill the whole fetch run
- **Separate config from code** → 12-Factor App, used by Shopify and DoorDash
- **Dedup by content hash** → How LinkedIn deduplicates feed stories at scale
