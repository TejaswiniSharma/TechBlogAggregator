"""
Tests for web/app.py — Flask routes and API endpoints.
Priority 4: User-facing. Bugs here are immediately visible.
"""

import json
import pytest
from unittest.mock import patch
from datetime import datetime
from tests.conftest import make_article
from fetcher.storage import add_articles


# ── Route status codes ────────────────────────────────────────────────────────

class TestRoutes:
    def test_home_returns_200(self, flask_client):
        resp = flask_client.get("/")
        assert resp.status_code == 200

    def test_archives_returns_200(self, flask_client):
        resp = flask_client.get("/archives")
        assert resp.status_code == 200

    def test_bookmarks_returns_200(self, flask_client):
        resp = flask_client.get("/bookmarks")
        assert resp.status_code == 200

    def test_notes_returns_200(self, flask_client):
        resp = flask_client.get("/notes")
        assert resp.status_code == 200

    def test_about_returns_200(self, flask_client):
        resp = flask_client.get("/about")
        assert resp.status_code == 200


# ── Homepage ──────────────────────────────────────────────────────────────────

class TestHomePage:
    def test_shows_article_titles(self, flask_client):
        resp = flask_client.get("/")
        html = resp.data.decode()
        assert "Test Article 1 from Netflix" in html

    def test_shows_company_name(self, flask_client):
        resp = flask_client.get("/")
        html = resp.data.decode()
        assert "Netflix" in html

    def test_tag_filter(self, flask_client):
        resp = flask_client.get("/?tag=caching")
        html = resp.data.decode()
        assert "Netflix" in html
        # Uber article has distributed-systems tag, not caching
        assert "Test Article 2 from Uber" not in html

    def test_contains_greeting(self, flask_client):
        resp = flask_client.get("/")
        html = resp.data.decode()
        assert any(g in html for g in ["Good morning", "Good afternoon", "Good evening"])

    def test_contains_stats(self, flask_client):
        resp = flask_client.get("/")
        html = resp.data.decode()
        assert "NEW THIS WEEK" in html.upper() or "new this week" in html.lower()


# ── Archives ──────────────────────────────────────────────────────────────────

class TestArchives:
    def test_shows_week_labels(self, flask_client):
        resp = flask_client.get("/archives")
        html = resp.data.decode()
        # Archives skips the latest 2 weeks; shows older weeks with fetch date format
        assert "Fetched" in html
        assert "articles from" in html

    def test_tag_filter(self, flask_client):
        resp = flask_client.get("/archives?tag=caching")
        html = resp.data.decode()
        assert resp.status_code == 200


# ── Bookmarks ─────────────────────────────────────────────────────────────────

class TestBookmarks:
    def test_empty_bookmarks(self, flask_client):
        resp = flask_client.get("/bookmarks")
        html = resp.data.decode()
        assert "No bookmarks yet" in html

    def test_shows_bookmarked_articles(self, flask_client):
        # Bookmark an article first
        flask_client.post("/api/bookmark",
                          data=json.dumps({"article_id": "test0001"}),
                          content_type="application/json")
        resp = flask_client.get("/bookmarks")
        html = resp.data.decode()
        assert "Test Article 1 from Netflix" in html


# ── Bookmark API ──────────────────────────────────────────────────────────────

class TestBookmarkAPI:
    def test_toggle_on(self, flask_client):
        resp = flask_client.post("/api/bookmark",
                                 data=json.dumps({"article_id": "test0001"}),
                                 content_type="application/json")
        data = json.loads(resp.data)
        assert resp.status_code == 200
        assert data["bookmarked"] is True
        assert data["total_bookmarks"] == 1

    def test_toggle_off(self, flask_client):
        # Toggle on
        flask_client.post("/api/bookmark",
                          data=json.dumps({"article_id": "test0001"}),
                          content_type="application/json")
        # Toggle off
        resp = flask_client.post("/api/bookmark",
                                 data=json.dumps({"article_id": "test0001"}),
                                 content_type="application/json")
        data = json.loads(resp.data)
        assert data["bookmarked"] is False
        assert data["total_bookmarks"] == 0

    def test_missing_id_returns_400(self, flask_client):
        resp = flask_client.post("/api/bookmark",
                                 data=json.dumps({}),
                                 content_type="application/json")
        assert resp.status_code == 400

    def test_nonexistent_id_returns_404(self, flask_client):
        resp = flask_client.post("/api/bookmark",
                                 data=json.dumps({"article_id": "nonexistent"}),
                                 content_type="application/json")
        assert resp.status_code == 404


# ── Notes API ─────────────────────────────────────────────────────────────────

class TestNotesAPI:
    def test_create_note(self, flask_client):
        resp = flask_client.post("/api/notes",
                                 data=json.dumps({
                                     "article_id": "test0001",
                                     "content": "Key takeaway: consistent hashing"
                                 }),
                                 content_type="application/json")
        data = json.loads(resp.data)
        assert resp.status_code == 200
        assert data["ok"] is True

    def test_update_note(self, flask_client):
        # Create first
        flask_client.post("/api/notes",
                          data=json.dumps({
                              "article_id": "test0001",
                              "content": "Initial note"
                          }),
                          content_type="application/json")
        # Update (note_id = 1 since it's the first note)
        resp = flask_client.post("/api/notes",
                                 data=json.dumps({
                                     "note_id": 1,
                                     "article_id": "test0001",
                                     "content": "Updated note"
                                 }),
                                 content_type="application/json")
        data = json.loads(resp.data)
        assert data["ok"] is True

    def test_missing_fields_returns_400(self, flask_client):
        resp = flask_client.post("/api/notes",
                                 data=json.dumps({"article_id": "test0001"}),
                                 content_type="application/json")
        assert resp.status_code == 400

    def test_delete_note(self, flask_client):
        # Create a note
        flask_client.post("/api/notes",
                          data=json.dumps({
                              "article_id": "test0001",
                              "content": "To be deleted"
                          }),
                          content_type="application/json")
        # Delete it
        resp = flask_client.delete("/api/notes/1")
        data = json.loads(resp.data)
        assert resp.status_code == 200
        assert data["ok"] is True


# ── Helper functions ──────────────────────────────────────────────────────────

class TestHelpers:
    def test_get_source_style_known(self):
        from web.app import get_source_style
        style = get_source_style("Netflix")
        assert style["bg"] == "#F5EDE5"
        assert style["text"] == "#8B5E3C"

    def test_get_source_style_unknown(self):
        from web.app import get_source_style
        style = get_source_style("UnknownCo")
        assert "bg" in style
        assert "text" in style

    def test_get_greeting_morning(self):
        from web.app import get_greeting
        with patch("web.app.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 3, 9, 0)
            mock_dt.strptime = datetime.strptime
            mock_dt.utcnow = datetime.utcnow
            assert get_greeting() == "Good morning"

    def test_get_greeting_afternoon(self):
        from web.app import get_greeting
        with patch("web.app.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 3, 14, 0)
            mock_dt.strptime = datetime.strptime
            mock_dt.utcnow = datetime.utcnow
            assert get_greeting() == "Good afternoon"

    def test_get_greeting_evening(self):
        from web.app import get_greeting
        with patch("web.app.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 3, 20, 0)
            mock_dt.strptime = datetime.strptime
            mock_dt.utcnow = datetime.utcnow
            assert get_greeting() == "Good evening"

    def test_parse_tags_valid(self):
        from web.app import parse_tags
        assert parse_tags('["a", "b"]') == ["a", "b"]

    def test_parse_tags_invalid(self):
        from web.app import parse_tags
        assert parse_tags("not json") == []

    def test_parse_tags_none(self):
        from web.app import parse_tags
        assert parse_tags(None) == []

    def test_parse_tags_empty_string(self):
        from web.app import parse_tags
        assert parse_tags("") == []
