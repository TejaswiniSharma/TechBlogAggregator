"""
Tests for fetcher/web_scraper.py — Playwright-based LinkedIn scraper.
Priority 6: Lowest priority, only handles one blog.
"""

import hashlib
import pytest
from unittest.mock import patch, MagicMock


class TestBuildArticle:
    """Test the article-building logic without Playwright."""

    def test_article_schema(self):
        from fetcher.web_scraper import _build_article
        blog_config = {
            "name": "LinkedIn Engineering",
            "company": "LinkedIn",
            "tags_hint": ["distributed-systems"],
        }
        result = _build_article(
            url="https://www.linkedin.com/blog/engineering/search/reimagining-search",
            title="Reimagining Search",
            blog_config=blog_config,
        )
        # Verify all required keys exist
        required_keys = ["id", "url", "title", "summary", "company", "blog_name",
                         "tags", "tags_hint", "published", "fetched_at", "status"]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_deterministic_id(self):
        from fetcher.web_scraper import _build_article
        config = {"name": "Blog", "company": "Co", "tags_hint": []}
        url = "https://example.com/article"
        a1 = _build_article(url, "Title", config)
        a2 = _build_article(url, "Title", config)
        assert a1["id"] == a2["id"]

    def test_id_matches_md5(self):
        from fetcher.web_scraper import _build_article
        config = {"name": "Blog", "company": "Co", "tags_hint": []}
        url = "https://example.com/article"
        result = _build_article(url, "Title", config)
        expected_id = hashlib.md5(url.encode()).hexdigest()[:12]
        assert result["id"] == expected_id

    def test_empty_summary(self):
        from fetcher.web_scraper import _build_article
        config = {"name": "Blog", "company": "Co", "tags_hint": []}
        result = _build_article("https://example.com/a", "Title", config)
        assert result["summary"] == ""


class TestScrapeBlog:
    @patch("playwright.sync_api.sync_playwright")
    def test_exception_returns_empty(self, mock_playwright):
        mock_playwright.return_value.__enter__ = MagicMock(side_effect=Exception("Browser crash"))
        mock_playwright.return_value.__exit__ = MagicMock(return_value=False)

        from fetcher.web_scraper import scrape_blog
        config = {
            "name": "LinkedIn Engineering",
            "company": "LinkedIn",
            "scrape_url": "https://www.linkedin.com/blog/engineering/",
            "tags_hint": [],
        }
        result = scrape_blog(config)
        assert result == []
