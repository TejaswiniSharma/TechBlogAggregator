"""
Tests for fetcher/rss_fetcher.py — RSS feed parser.
Priority 3: Network-dependent code. Mocks feedparser.parse.
"""

import hashlib
import pytest
from unittest.mock import patch, MagicMock
from fetcher.rss_fetcher import fetch_blog, _normalize_entry, _strip_html, fetch_all_blogs


# ── _strip_html ───────────────────────────────────────────────────────────────

class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_handles_nested_tags(self):
        assert _strip_html("<div><p><span>deep</span></p></div>") == "deep"

    def test_collapses_whitespace(self):
        result = _strip_html("<p>Hello</p>   \n  <p>world</p>")
        assert result == "Hello world"

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_no_tags(self):
        assert _strip_html("plain text here") == "plain text here"

    def test_unclosed_tag(self):
        result = _strip_html("<p>Hello <b>world")
        assert "Hello" in result
        assert "world" in result


# ── _normalize_entry ──────────────────────────────────────────────────────────

class TestNormalizeEntry:
    @pytest.fixture
    def blog_config(self):
        return {
            "name": "Netflix Tech Blog",
            "company": "Netflix",
            "rss_url": "https://netflixtechblog.com/feed",
            "tags_hint": ["distributed-systems", "microservices"],
        }

    @pytest.fixture
    def feed_entry(self):
        entry = MagicMock()
        entry.get = lambda key, default="": {
            "link": "https://netflixtechblog.com/scaling-cache-123",
            "title": "Scaling Cache at Netflix",
            "summary": "How Netflix handles cache invalidation at scale.",
        }.get(key, default)
        entry.published_parsed = None
        return entry

    def test_complete_entry(self, feed_entry, blog_config):
        result = _normalize_entry(feed_entry, blog_config)
        assert result is not None
        assert result["url"] == "https://netflixtechblog.com/scaling-cache-123"
        assert result["title"] == "Scaling Cache at Netflix"
        assert result["company"] == "Netflix"
        assert result["blog_name"] == "Netflix Tech Blog"
        assert result["status"] == "new"
        assert isinstance(result["tags"], list)
        assert len(result["id"]) == 12

    def test_missing_link_returns_none(self, blog_config):
        entry = MagicMock()
        entry.get = lambda key, default="": "" if key == "link" else default
        result = _normalize_entry(entry, blog_config)
        assert result is None

    def test_deterministic_id(self, feed_entry, blog_config):
        result1 = _normalize_entry(feed_entry, blog_config)
        result2 = _normalize_entry(feed_entry, blog_config)
        assert result1["id"] == result2["id"]

    def test_id_is_md5_prefix(self, feed_entry, blog_config):
        result = _normalize_entry(feed_entry, blog_config)
        expected = hashlib.md5("https://netflixtechblog.com/scaling-cache-123".encode()).hexdigest()[:12]
        assert result["id"] == expected

    def test_truncates_summary_at_500(self, blog_config):
        long_summary = "x" * 1000
        entry = MagicMock()
        entry.get = lambda key, default="": {
            "link": "https://example.com/long",
            "title": "Long Article",
            "summary": long_summary,
        }.get(key, default)
        entry.published_parsed = None
        result = _normalize_entry(entry, blog_config)
        assert len(result["summary"]) <= 500


# ── fetch_blog ────────────────────────────────────────────────────────────────

class TestFetchBlog:
    @pytest.fixture
    def blog_config(self):
        return {
            "name": "Test Blog",
            "company": "TestCo",
            "rss_url": "https://test.com/feed",
            "tags_hint": ["general"],
        }

    def _mock_feed(self, entries, bozo=False):
        feed = MagicMock()
        feed.bozo = bozo
        feed.entries = entries
        return feed

    def _mock_entry(self, url, title):
        entry = MagicMock()
        entry.get = lambda key, default="": {
            "link": url,
            "title": title,
            "summary": f"Summary of {title}",
        }.get(key, default)
        entry.published_parsed = None
        return entry

    @patch("fetcher.rss_fetcher.feedparser.parse")
    def test_success(self, mock_parse, blog_config):
        entries = [
            self._mock_entry("https://test.com/1", "Article 1"),
            self._mock_entry("https://test.com/2", "Article 2"),
        ]
        mock_parse.return_value = self._mock_feed(entries)
        articles = fetch_blog(blog_config)
        assert len(articles) == 2
        assert articles[0]["company"] == "TestCo"

    @patch("fetcher.rss_fetcher.feedparser.parse")
    def test_empty_feed(self, mock_parse, blog_config):
        mock_parse.return_value = self._mock_feed([])
        articles = fetch_blog(blog_config)
        assert articles == []

    @patch("fetcher.rss_fetcher.feedparser.parse")
    def test_bozo_feed_no_entries(self, mock_parse, blog_config):
        mock_parse.return_value = self._mock_feed([], bozo=True)
        articles = fetch_blog(blog_config)
        assert articles == []

    @patch("fetcher.rss_fetcher.feedparser.parse")
    def test_bozo_feed_with_entries(self, mock_parse, blog_config):
        entries = [self._mock_entry("https://test.com/1", "Article 1")]
        mock_parse.return_value = self._mock_feed(entries, bozo=True)
        articles = fetch_blog(blog_config)
        assert len(articles) == 1

    @patch("fetcher.rss_fetcher.feedparser.parse")
    def test_exception_returns_empty(self, mock_parse, blog_config):
        mock_parse.side_effect = Exception("Network error")
        articles = fetch_blog(blog_config)
        assert articles == []


# ── fetch_all_blogs ───────────────────────────────────────────────────────────

class TestFetchAllBlogs:
    @patch("fetcher.rss_fetcher.feedparser.parse")
    def test_routes_rss_config(self, mock_parse):
        entry = MagicMock()
        entry.get = lambda key, default="": {
            "link": "https://test.com/article",
            "title": "Test",
            "summary": "Summary",
        }.get(key, default)
        entry.published_parsed = None

        feed = MagicMock()
        feed.bozo = False
        feed.entries = [entry]
        mock_parse.return_value = feed

        configs = [{"name": "Blog", "company": "Co", "rss_url": "https://test.com/feed", "tags_hint": []}]
        articles = fetch_all_blogs(configs)
        assert len(articles) == 1
