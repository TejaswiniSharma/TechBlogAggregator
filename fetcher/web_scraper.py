# fetcher/web_scraper.py
#
# WHY THIS FILE EXISTS:
# Some blogs (LinkedIn Engineering) don't publish RSS feeds AND are JavaScript-rendered
# SPAs — meaning urllib gets a blank HTML shell with no article data.
# We use Playwright (headless Chromium) to fully render the page and then
# extract articles from the real DOM.
#
# WHY Playwright over urllib/BeautifulSoup?
# LinkedIn's blog is a React SPA. The server sends a JS bundle; the browser
# runs it and renders the article listing. urllib only gets the empty shell.
# Playwright launches a real browser, waits for JS to execute, THEN reads the DOM.
# This is the same reason Googlebot uses a headless browser for JS-heavy sites.
#
# WHY not Selenium?
# Playwright is faster (async-native), has better auto-wait logic, and
# doesn't require a separately installed WebDriver. One pip install + one
# browser download and it works.
#
# DESIGN: same output schema as rss_fetcher.fetch_blog()
# Both return list[dict] with the same fields.
# Callers (fetch_all_blogs, storage.py) don't know or care which path ran.
# This is the 'adapter pattern'.

import hashlib
import re
from datetime import datetime
from fetcher.topic_tagger import tag_article


def scrape_blog(blog_config: dict) -> list[dict]:
    """
    Scrape articles from a JS-rendered blog using Playwright.

    Args:
        blog_config: Blog config entry with 'scrape_url', 'name', 'company', 'tags_hint'.

    Returns:
        List of normalized article dicts — same schema as rss_fetcher.fetch_blog().
    """
    scrape_url = blog_config.get("scrape_url", "")
    print(f"  Scraping: {blog_config['name']} (JS render)...", end=" ", flush=True)

    try:
        articles = _fetch_with_playwright(scrape_url, blog_config)
        print(f"OK — {len(articles)} articles")
        return articles
    except Exception as e:
        print(f"ERROR: {e}")
        return []


def _fetch_with_playwright(url: str, blog_config: dict) -> list[dict]:
    """
    Launch headless Chromium, load the page, wait for JS to render,
    then extract article links and titles from the DOM.

    WHY sync_playwright (not async)?
    The rest of the system is synchronous. Using async here would require
    async-all-the-way-up, touching fetch_all_blogs, run_fetch.py, etc.
    sync_playwright wraps the async internals — same result, no ripple effect.

    WHY wait_for_selector?
    SPAs render in stages. If we read the DOM immediately, we get the loading
    skeleton. Waiting for an <a> tag with the expected URL pattern ensures
    the article list has actually rendered before we extract it.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Block images, fonts, media — we only need HTML/JS/CSS
        # WHY? Speeds up load by ~60%; we don't need visual assets.
        page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,mp4,webm}", lambda r: r.abort())

        # WHY networkidle? LinkedIn is a React SPA that fetches article data
        # after the initial JS bundle executes. networkidle waits until all
        # XHR/fetch calls settle — that's when the article list is populated.
        page.goto(url, wait_until="networkidle", timeout=25000)

        # Scroll to trigger any lazy-loaded content below the fold
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)

        # Extract all <a> tags — we filter to article-depth URLs below
        links = page.eval_on_selector_all(
            "a",
            """
            elements => elements.map(el => ({
                href: el.getAttribute('href') || '',
                text: el.innerText.trim()
            }))
            """
        )

        browser.close()

    # Filter to article-depth URLs: .../blog/engineering/<category>/<slug>
    # LinkedIn returns absolute URLs (https://www.linkedin.com/blog/...)
    articles = []
    seen_hrefs = set()
    for link in links:
        href = link.get("href", "")
        title = link.get("text", "").strip()

        # Normalise: accept both absolute and relative forms
        if href.startswith("https://www.linkedin.com"):
            full_url = href
        elif href.startswith("/blog/engineering/"):
            full_url = "https://www.linkedin.com" + href
        else:
            continue

        # Must be article-depth: 4 path segments minimum
        # e.g. /blog/engineering/ai/some-article-slug  ✓
        # e.g. /blog/engineering/ai                    ✗  (category page)
        if not re.search(r"/blog/engineering/[^/]+/[^/?#]+", full_url):
            continue
        if not title or len(title) < 15:
            continue
        if full_url in seen_hrefs:
            continue

        seen_hrefs.add(full_url)
        articles.append(_build_article(full_url, title, blog_config))

    return articles


def _build_article(url: str, title: str, blog_config: dict) -> dict:
    """
    Build a normalized article dict from a scraped title + URL.

    WHY is summary empty?
    Fetching each article page to extract a summary would mean 10-15 extra
    browser launches per run — too slow. Summary stays empty for scraped blogs.
    The AI tagger (Subsystem 2) works well from title + tags_hint alone.
    """
    article_id = hashlib.md5(url.encode()).hexdigest()[:12]
    tags = tag_article(title, "")

    return {
        "id": article_id,
        "url": url,
        "title": title,
        "summary": "",
        "company": blog_config["company"],
        "blog_name": blog_config["name"],
        "tags": tags,
        "tags_hint": blog_config.get("tags_hint", []),
        "published": "",
        "fetched_at": datetime.utcnow().isoformat(),
        "status": "new",
    }
