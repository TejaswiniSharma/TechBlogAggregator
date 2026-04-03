"""
Tests for fetcher/storage.py — SQLite persistence layer.
Priority 1: Everything depends on this module.
"""

import json
import pytest
from tests.conftest import make_article
from fetcher.storage import (
    add_articles,
    get_articles,
    update_article_ai_analysis,
    update_article_status,
    _get_week_label,
)


# ── add_articles ──────────────────────────────────────────────────────────────

class TestAddArticles:
    def test_inserts_new(self, tmp_db):
        articles = [make_article(1), make_article(2), make_article(3)]
        result = add_articles(articles)
        assert result["added"] == 3
        assert result["skipped"] == 0
        assert result["total"] == 3

    def test_skips_duplicate_url(self, tmp_db):
        articles = [make_article(1)]
        add_articles(articles)
        result = add_articles(articles)  # same article again
        assert result["added"] == 0
        assert result["skipped"] == 1
        assert result["total"] == 1

    def test_mixed_new_and_duplicate(self, tmp_db):
        add_articles([make_article(1)])
        result = add_articles([make_article(1), make_article(2)])
        assert result["added"] == 1
        assert result["skipped"] == 1
        assert result["total"] == 2

    def test_handles_missing_optional_fields(self, tmp_db):
        minimal = {
            "id": "minimal01",
            "url": "https://example.com/minimal",
            "title": "Minimal Article",
            "company": "TestCo",
            "fetched_at": "2026-04-01T10:00:00",
        }
        result = add_articles([minimal])
        assert result["added"] == 1

        articles = get_articles()
        assert len(articles) == 1
        assert articles[0]["summary"] == ""
        assert articles[0]["tags"] == []


# ── get_articles ──────────────────────────────────────────────────────────────

class TestGetArticles:
    def test_no_filters_returns_all(self, tmp_db):
        add_articles([make_article(1), make_article(2), make_article(3)])
        articles = get_articles()
        assert len(articles) == 3

    def test_ordered_by_fetched_at_desc(self, tmp_db):
        add_articles([make_article(1), make_article(2), make_article(3)])
        articles = get_articles()
        dates = [a["fetched_at"] for a in articles]
        assert dates == sorted(dates, reverse=True)

    def test_filter_by_company(self, tmp_db):
        add_articles([
            make_article(1, company="Netflix"),
            make_article(2, company="Uber"),
            make_article(3, company="Netflix"),
        ])
        articles = get_articles(company="Netflix")
        assert len(articles) == 2
        assert all(a["company"] == "Netflix" for a in articles)

    def test_filter_by_topic(self, tmp_db):
        add_articles([
            make_article(1, tags=["caching"]),
            make_article(2, tags=["databases"]),
            make_article(3, tags=["caching", "databases"]),
        ])
        articles = get_articles(topic="caching")
        assert len(articles) == 2

    def test_filter_by_status(self, tmp_db):
        add_articles([
            make_article(1, status="new"),
            make_article(2, status="done"),
        ])
        articles = get_articles(status="new")
        assert len(articles) == 1
        assert articles[0]["status"] == "new"

    def test_with_limit(self, tmp_db):
        add_articles([make_article(i) for i in range(1, 11)])
        articles = get_articles(limit=3)
        assert len(articles) == 3

    def test_empty_db_returns_empty_list(self, tmp_db):
        articles = get_articles()
        assert articles == []


# ── update_article_ai_analysis ────────────────────────────────────────────────

class TestUpdateAiAnalysis:
    def test_success(self, tmp_db):
        add_articles([make_article(1)])
        analysis = {
            "ai_summary": {
                "problem": "Scaling cache invalidation",
                "solution": "Used consistent hashing with TTL",
                "concepts": ["consistent hashing", "TTL"],
                "study_summary": "A study in caching",
            },
            "tags": ["caching", "distributed-systems"],
        }
        result = update_article_ai_analysis("https://example.com/blog/article-1", analysis)
        assert result is True

        articles = get_articles()
        a = articles[0]
        assert a["ai_problem"] == "Scaling cache invalidation"
        assert a["ai_solution"] == "Used consistent hashing with TTL"
        assert "ai_summary" in a
        assert a["ai_summary"]["concepts"] == ["consistent hashing", "TTL"]
        assert a["tags"] == ["caching", "distributed-systems"]
        assert a["ai_tagged_at"] is not None

    def test_nonexistent_url_returns_false(self, tmp_db):
        add_articles([make_article(1)])
        analysis = {
            "ai_summary": {"problem": "x", "solution": "y", "concepts": []},
            "tags": ["general"],
        }
        result = update_article_ai_analysis("https://nonexistent.com", analysis)
        assert result is False


# ── update_article_status ─────────────────────────────────────────────────────

class TestUpdateStatus:
    def test_success(self, tmp_db):
        add_articles([make_article(1)])
        result = update_article_status("https://example.com/blog/article-1", "in-progress")
        assert result is True

    def test_nonexistent_url_returns_false(self, tmp_db):
        result = update_article_status("https://nonexistent.com", "done")
        assert result is False


# ── _get_week_label ───────────────────────────────────────────────────────────

class TestGetWeekLabel:
    def test_valid_iso_date(self):
        assert _get_week_label("2026-03-30T10:00:00") == "2026-W14"

    def test_empty_string(self):
        assert _get_week_label("") == ""

    def test_none(self):
        assert _get_week_label(None) == ""

    def test_malformed_date(self):
        assert _get_week_label("not-a-date") == ""

    def test_date_with_timezone(self):
        result = _get_week_label("2026-03-30T10:00:00Z")
        assert result == "2026-W14"


# ── _row_to_dict ──────────────────────────────────────────────────────────────

class TestRowToDict:
    def test_parses_json_fields(self, tmp_db):
        add_articles([make_article(1, tags=["caching", "databases"])])
        articles = get_articles()
        assert articles[0]["tags"] == ["caching", "databases"]
        assert isinstance(articles[0]["tags_hint"], list)

    def test_reconstructs_ai_summary_when_valid(self, tmp_db):
        add_articles([make_article(1)])
        update_article_ai_analysis("https://example.com/blog/article-1", {
            "ai_summary": {
                "problem": "Real problem",
                "solution": "Real solution",
                "concepts": ["concept1"],
                "study_summary": "",
            },
            "tags": ["caching"],
        })
        articles = get_articles()
        assert "ai_summary" in articles[0]
        assert articles[0]["ai_summary"]["problem"] == "Real problem"

    def test_no_ai_summary_when_parse_failed(self, tmp_db):
        add_articles([make_article(1)])
        update_article_ai_analysis("https://example.com/blog/article-1", {
            "ai_summary": {
                "problem": "Could not parse AI response.",
                "solution": "Could not parse AI response.",
                "concepts": [],
                "study_summary": "",
            },
            "tags": ["general"],
        })
        articles = get_articles()
        assert "ai_summary" not in articles[0]
