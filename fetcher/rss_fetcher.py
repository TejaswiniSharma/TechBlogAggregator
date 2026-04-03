# fetcher/rss_fetcher.py
#
# WHY THIS FILE EXISTS:
# This is the core engine of Subsystem 1. It knows how to:
#   1. Talk to RSS feeds (pull articles from big tech blogs)
#   2. Normalize different feed formats into our standard schema
#   3. Tag each article with interview topics
#
# ARCHITECTURE DECISION — WHY RSS and not web scraping?
# RSS is a contract. When Netflix publishes a post, their CMS generates a clean RSS feed.
# Web scraping breaks every time a company redesigns their blog (CSS class names change,
# DOM structure shifts). RSS gives us structured data without fragility.
# LinkedIn Engineering's blog explicitly publishes an RSS feed for this purpose.
#
# WHY 'feedparser' library?
# RSS has 3 major versions (RSS 0.9, RSS 2.0, Atom) plus countless proprietary quirks.
# feedparser normalizes ALL of them into one consistent object.
# This is the same "normalize at the boundary" principle that microservices use
# when they have to talk to multiple external APIs.

import feedparser
import hashlib
from datetime import datetime, timezone
from typing import Optional
from fetcher.topic_tagger import tag_article


def fetch_blog(blog_config: dict) -> list[dict]:
    """
    Fetch articles from a single blog's RSS feed.

    Args:
        blog_config: One entry from config/blogs.py (name, company, rss_url, tags_hint)

    Returns:
        List of normalized article dicts ready to be stored.

    WHY normalize inside fetch_blog and not in storage.py?
    Normalization belongs at the point of ingestion — the 'intake' layer.
    By the time data reaches storage, it should already be in our schema.
    This way, storage.py never has to know anything about RSS-specific fields.
    (Stripe Engineering wrote a great post about this: 'normalize at the border'.)
    """
    print(f"  Fetching: {blog_config['name']}...", end=" ", flush=True)

    try:
        # feedparser handles the HTTP request AND the parsing
        # WHY not use requests + BeautifulSoup?
        # Two libraries to maintain vs one. feedparser is purpose-built for this.
        feed = feedparser.parse(blog_config["rss_url"])

        # Check if the fetch failed (feedparser doesn't raise exceptions — it sets bozo=True)
        # WHY 'bozo'? It's feedparser's quirky name for malformed/unreachable feeds.
        # Real code should check this in production.
        if feed.bozo and not feed.entries:
            print(f"FAILED (feed unreachable or malformed)")
            return []

        articles = []
        for entry in feed.entries:
            article = _normalize_entry(entry, blog_config)
            if article:
                articles.append(article)

        print(f"OK — {len(articles)} articles")
        return articles

    except Exception as e:
        # WHY catch all exceptions here?
        # One bad feed should NOT stop the entire fetch run.
        # If Netflix's RSS is down, we still want Spotify and Uber articles.
        # This is the 'bulkhead pattern' — isolate failures.
        print(f"ERROR: {e}")
        return []


def _normalize_entry(entry: feedparser.FeedParserDict, blog_config: dict) -> Optional[dict]:
    """
    Convert one RSS entry into our standard article schema.

    The leading underscore signals 'private to this module' — Python convention,
    not enforcement. Callers use fetch_blog(), not this.

    WHY define a fixed schema?
    Subsystem 2, 3, and 4 will all read from articles.json.
    If each subsystem has to handle quirks of different RSS formats,
    you'll have bugs spread across the codebase. Normalize ONCE here.

    Our schema:
    {
        id:          unique fingerprint (md5 of URL)
        url:         canonical article URL
        title:       article title
        summary:     first ~500 chars of description
        company:     e.g. "Netflix"
        blog_name:   e.g. "Netflix Tech Blog"
        tags:        list of system design topics (from topic_tagger)
        tags_hint:   blog's known topic areas (from config)
        published:   ISO 8601 date string
        fetched_at:  when WE fetched it (for dedup and sorting)
        status:      "new" | "in-progress" | "done" (managed by Subsystem 4)
    }
    """
    # --- URL ---
    url = entry.get("link", "")
    if not url:
        return None  # No URL = useless entry, skip it

    # --- ID ---
    # WHY hash the URL instead of using a counter or UUID?
    # Hash is DETERMINISTIC. If the same article appears in two fetch runs,
    # it gets the same ID. UUIDs would give it a different ID each time → duplicates.
    article_id = hashlib.md5(url.encode()).hexdigest()[:12]

    # --- Title ---
    title = entry.get("title", "Untitled").strip()

    # --- Summary ---
    # RSS 'summary' field exists in most feeds; 'description' is the fallback.
    # We cap at 500 chars because: (1) we don't need the full article, just enough
    # to tag topics, and (2) storage stays compact.
    raw_summary = entry.get("summary", entry.get("description", ""))
    # Strip basic HTML tags (feedparser often leaves some behind)
    summary = _strip_html(raw_summary)[:500]

    # --- Published date ---
    # feedparser provides 'published_parsed' as a time.struct_time object
    published = ""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            published = dt.isoformat()
        except Exception:
            published = entry.get("published", "")

    # --- Tags ---
    # Run our keyword tagger on title + summary
    tags = tag_article(title, summary)

    return {
        "id": article_id,
        "url": url,
        "title": title,
        "summary": summary,
        "company": blog_config["company"],
        "blog_name": blog_config["name"],
        "tags": tags,
        "tags_hint": blog_config.get("tags_hint", []),
        "published": published,
        "fetched_at": datetime.utcnow().isoformat(),
        "status": "new",  # Subsystem 4 will update this as you study
    }


def _strip_html(text: str) -> str:
    """
    Remove basic HTML tags from text using string operations.

    WHY not use BeautifulSoup or lxml?
    For this specific task (rough cleanup of RSS summaries), regex or simple
    state machine is faster and dependency-free. We don't need a full HTML parser
    for 500 chars of preview text.

    WHY a manual state machine instead of regex?
    Regex struggles with nested/malformed HTML (and RSS feeds often have it).
    A simple char-by-char state machine is more robust and easier to reason about.
    """
    result = []
    inside_tag = False
    for char in text:
        if char == "<":
            inside_tag = True
        elif char == ">":
            inside_tag = False
        elif not inside_tag:
            result.append(char)

    # Collapse multiple spaces/newlines left after tag removal
    return " ".join("".join(result).split())


def fetch_all_blogs(blog_configs: list[dict]) -> list[dict]:
    """
    Fetch from all configured blogs, routing to the right fetcher per blog.

    Blogs with 'rss_url'   → fetch_blog()  (RSS/Atom via feedparser)
    Blogs with 'scrape_url' → scrape_blog() (HTML scraper for RSS-less blogs)

    WHY check the config key to decide the fetcher?
    The blog config IS the contract. Callers don't need to know which path
    was taken — they just get back the same list[dict] either way.
    This is the 'strategy pattern': swap the fetch strategy without changing
    the interface.

    WHY sequential (not parallel/async)?
    LEARNING DECISION: Start synchronous. Once this works and you understand
    what's slow, THEN add concurrency. Premature parallelism introduces race
    conditions that are brutal to debug.

    INTERVIEW INSIGHT:
    This is exactly the conversation Netflix has in system design interviews:
    "Start with polling (sync fetch), then move to event-driven (webhooks/RSS push)."
    """
    from fetcher.web_scraper import scrape_blog

    all_articles = []
    for blog_config in blog_configs:
        if "scrape_url" in blog_config:
            articles = scrape_blog(blog_config)
        else:
            articles = fetch_blog(blog_config)
        all_articles.extend(articles)
    return all_articles
