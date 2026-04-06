"""
Shared test fixtures for the Tech Blog Aggregator test suite.
"""

import json
import os
import sqlite3
import pytest

# Ensure project root is importable
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_article(
    idx=1,
    company="Netflix",
    title=None,
    tags=None,
    summary="A test article summary about distributed systems.",
    status="new",
    ai_problem=None,
):
    """Build a complete article dict with all required fields."""
    return {
        "id": f"test{idx:04d}",
        "url": f"https://example.com/blog/article-{idx}",
        "title": title or f"Test Article {idx} from {company}",
        "summary": summary,
        "company": company,
        "blog_name": f"{company} Engineering Blog",
        "tags": tags or ["distributed-systems"],
        "tags_hint": ["infrastructure"],
        "published": "2026-03-30T10:00:00",
        "fetched_at": f"2026-03-30T{10 + idx:02d}:00:00",
        "status": status,
    }


@pytest.fixture
def sample_article():
    """Returns a single complete article dict."""
    return make_article()


@pytest.fixture
def sample_articles():
    """Factory fixture — call with n to get n unique articles."""
    def _make(n, **kwargs):
        return [make_article(idx=i + 1, **kwargs) for i in range(n)]
    return _make


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """
    Create a temporary SQLite database and patch storage.DB_FILE to use it.
    Returns the path to the temp DB file.
    """
    import fetcher.storage as storage
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(storage, "DB_FILE", db_path)
    return db_path


@pytest.fixture
def flask_client(tmp_db, monkeypatch):
    """
    Flask test client with a temporary database.
    """
    import web.app as web_app
    monkeypatch.setattr(web_app, "DB_FILE", tmp_db)

    # Initialize tables via storage (which is already patched to tmp_db)
    from fetcher.storage import add_articles
    add_articles([
        make_article(1, company="Netflix", tags=["caching"], summary="Redis caching at scale"),
        make_article(2, company="Uber", tags=["distributed-systems"], summary="Uber's distributed tracing"),
        make_article(3, company="Netflix", tags=["caching", "databases"], summary="Caching with DynamoDB"),
        # Articles across 3 weeks so archives (which skips latest 2) has data
        {**make_article(4, company="Airbnb", tags=["microservices"], summary="Airbnb service mesh"),
         "published": "2026-03-23T10:00:00", "fetched_at": "2026-03-23T10:00:00"},
        {**make_article(5, company="Meta", tags=["ml-systems"], summary="Meta ML infra"),
         "published": "2026-03-16T10:00:00", "fetched_at": "2026-03-16T10:00:00"},
    ])

    web_app.app.config["TESTING"] = True
    with web_app.app.test_client() as client:
        with web_app.app.app_context():
            yield client
