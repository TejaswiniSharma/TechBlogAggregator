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

    def test_contains_stats(self, flask_client):
        resp = flask_client.get("/")
        html = resp.data.decode()
        assert "NEW THIS WEEK" in html.upper() or "new this week" in html.lower()


# ── Archives ──────────────────────────────────────────────────────────────────

class TestArchives:
    def test_shows_week_labels(self, flask_client):
        resp = flask_client.get("/archives")
        html = resp.data.decode()
        # Archives skips the latest 2 weeks; shows older weeks as date ranges
        assert "2026" in html

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

    def test_update_note_allows_empty_content(self, flask_client):
        """Clearing the editor or saving whitespace-only must persist (regression)."""
        flask_client.post("/api/notes",
                          data=json.dumps({
                              "article_id": "test0001",
                              "content": "Initial note"
                          }),
                          content_type="application/json")
        resp = flask_client.post("/api/notes",
                                 data=json.dumps({
                                     "note_id": 1,
                                     "content": ""
                                 }),
                                 content_type="application/json")
        assert resp.status_code == 200
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


# ── Auth ─────────────────────────────────────────────────────────────────────

class TestAuth:
    # ── Pages accessible to anonymous users ───────────────────────────────────
    def test_login_page_returns_200(self, anon_client):
        resp = anon_client.get("/login")
        assert resp.status_code == 200

    def test_register_page_returns_200(self, anon_client):
        resp = anon_client.get("/register")
        assert resp.status_code == 200

    # ── Register ──────────────────────────────────────────────────────────────
    def test_register_creates_user_and_redirects(self, anon_client):
        resp = anon_client.post("/register", data={
            "username": "newuser",
            "password": "securepass1",
        }, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["Location"] in ("/", "http://localhost/")

    def test_register_duplicate_username_flashes_error(self, anon_client):
        # "testuser" already exists (created by fixture)
        resp = anon_client.post("/register", data={
            "username": "testuser",
            "password": "somepassword",
        }, follow_redirects=True)
        html = resp.data.decode()
        assert "already taken" in html

    def test_register_short_username_rejected(self, anon_client):
        resp = anon_client.post("/register", data={
            "username": "ab",
            "password": "securepass1",
        }, follow_redirects=True)
        assert "3" in resp.data.decode()  # "3–20 characters" message

    def test_register_short_password_rejected(self, anon_client):
        resp = anon_client.post("/register", data={
            "username": "validuser",
            "password": "short",
        }, follow_redirects=True)
        assert "8" in resp.data.decode()  # "at least 8 characters" message

    def test_register_non_alphanumeric_username_rejected(self, anon_client):
        resp = anon_client.post("/register", data={
            "username": "bad user!",
            "password": "securepass1",
        }, follow_redirects=True)
        assert "letters and numbers" in resp.data.decode().lower()

    # ── Login ─────────────────────────────────────────────────────────────────
    def test_login_valid_credentials_redirects(self, anon_client):
        resp = anon_client.post("/login", data={
            "username": "testuser",
            "password": "testpass123",
        }, follow_redirects=False)
        assert resp.status_code == 302

    def test_login_wrong_password_shows_error(self, anon_client):
        resp = anon_client.post("/login", data={
            "username": "testuser",
            "password": "wrongpassword",
        }, follow_redirects=True)
        assert "Invalid username or password" in resp.data.decode()

    def test_login_unknown_user_shows_error(self, anon_client):
        resp = anon_client.post("/login", data={
            "username": "nobody",
            "password": "testpass123",
        }, follow_redirects=True)
        assert "Invalid username or password" in resp.data.decode()

    # ── Logout ────────────────────────────────────────────────────────────────
    def test_logout_redirects_to_login(self, flask_client):
        resp = flask_client.post("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "login" in resp.headers["Location"]

    # ── Access control ────────────────────────────────────────────────────────
    def test_protected_routes_redirect_when_logged_out(self, anon_client):
        for path in ["/bookmarks", "/notes"]:
            resp = anon_client.get(path)
            assert resp.status_code == 302, f"{path} should redirect when logged out"
            assert "login" in resp.headers["Location"]

    def test_api_returns_401_when_logged_out(self, anon_client):
        resp = anon_client.post("/api/bookmark",
                                data=json.dumps({"article_id": "test0001"}),
                                content_type="application/json")
        assert resp.status_code == 401

    def test_public_routes_accessible_when_logged_out(self, anon_client):
        for path in ["/", "/archives", "/search", "/about", "/health"]:
            resp = anon_client.get(path)
            assert resp.status_code == 200, f"{path} should be public"

    # ── Navbar state ──────────────────────────────────────────────────────────
    def test_navbar_shows_logout_when_authenticated(self, flask_client):
        html = flask_client.get("/").data.decode()
        assert "log out" in html.lower()

    def test_navbar_shows_login_when_anonymous(self, anon_client):
        html = anon_client.get("/").data.decode()
        assert "log in" in html.lower()


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
