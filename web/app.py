#!/usr/bin/env python3
"""
Distributed Readings — Flask web app.
Serves the Botanical Morning-themed website for browsing tech blog articles.

Run locally: python3 web/app.py
"""

import json
import os
import sqlite3
import warnings
from datetime import datetime, timedelta

import click
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(PROJECT_ROOT, "data", "techblogs.db")


# ── Secret key (AWS Secrets Manager → env var → dev fallback) ─────────────────

def _load_secret_key() -> str:
    secret_name = os.environ.get("SECRET_KEY_NAME", "distributed-readings/secret-key")
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        return client.get_secret_value(SecretId=secret_name)["SecretString"]
    except Exception:
        pass
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    warnings.warn(
        "SECRET_KEY not configured — using insecure dev key. "
        "Set SECRET_KEY env var or configure AWS Secrets Manager.",
        stacklevel=2,
    )
    return "dev-only-insecure-key-do-not-use-in-production"


# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config.update(
    MAX_CONTENT_LENGTH=64 * 1024,
    SECRET_KEY=_load_secret_key(),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)

csrf = CSRFProtect(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


# ── User model ────────────────────────────────────────────────────────────────

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

    @staticmethod
    def get(user_id):
        row = query_db("SELECT id, username FROM users WHERE id = ?", (user_id,), one=True)
        return User(row["id"], row["username"]) if row else None

    @staticmethod
    def get_by_username(username):
        return query_db(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,), one=True,
        )


@login_manager.user_loader
def load_user(user_id):
    return User.get(int(user_id))


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/"):
        return jsonify({"error": "Authentication required"}), 401
    return redirect(url_for("login", next=request.url))


# ── Database helpers ──────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        _ensure_fts_tables(g.db)
        _ensure_auth_tables(g.db)
        _ensure_migration(g.db)
    return g.db


def _ensure_fts_tables(db):
    """Create FTS5 virtual tables and rebuild index if empty."""
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            title, summary, ai_problem, ai_solution,
            content='articles', content_rowid='rowid'
        )
    """)
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            content, content='notes', content_rowid='id'
        )
    """)
    db.commit()

    fts_data_rows = db.execute("SELECT COUNT(*) FROM articles_fts_data").fetchone()[0]
    if fts_data_rows <= 2:
        art_count = db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if art_count > 0:
            db.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
            db.commit()


def _ensure_auth_tables(db):
    """Create users and user_bookmarks tables."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_bookmarks (
            user_id    INTEGER NOT NULL REFERENCES users(id),
            article_id TEXT    NOT NULL REFERENCES articles(id),
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, article_id)
        );

        CREATE INDEX IF NOT EXISTS idx_user_bookmarks_user ON user_bookmarks(user_id);
    """)


def _ensure_migration(db):
    """
    Idempotent migration: adds user_id to notes and backfills existing
    notes + global bookmarks to the first (owner) user.
    Runs as a fast no-op after migration completes.
    """
    notes_exists = db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='notes'"
    ).fetchone()[0]
    if not notes_exists:
        return

    cols = {r[1] for r in db.execute("PRAGMA table_info(notes)").fetchall()}
    if "user_id" not in cols:
        db.execute("ALTER TABLE notes ADD COLUMN user_id INTEGER REFERENCES users(id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id)")
        db.commit()

    need_notes = db.execute(
        "SELECT COUNT(*) FROM notes WHERE user_id IS NULL"
    ).fetchone()[0] > 0
    need_bookmarks = (
        db.execute("SELECT COUNT(*) FROM user_bookmarks").fetchone()[0] == 0
        and db.execute("SELECT COUNT(*) FROM articles WHERE bookmarked = 1").fetchone()[0] > 0
    )

    if not need_notes and not need_bookmarks:
        return

    owner = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if not owner:
        return
    owner_id = owner["id"]

    if need_notes:
        db.execute("UPDATE notes SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    if need_bookmarks:
        db.execute("""
            INSERT OR IGNORE INTO user_bookmarks (user_id, article_id)
            SELECT ?, id FROM articles WHERE bookmarked = 1
        """, (owner_id,))
    db.commit()


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


# ── Company → color mapping (Botanical Morning palette) ───────────────────────

SOURCE_STYLES = {
    "Netflix":    {"bg": "#F5EDE5", "text": "#8B5E3C"},
    "Airbnb":     {"bg": "#FDF0F4", "text": "#B5527A"},
    "Uber":       {"bg": "#EFF5FA", "text": "#2E6A9E"},
    "LinkedIn":   {"bg": "#EFF5FA", "text": "#2E6A9E"},
    "Stripe":     {"bg": "#FDF0F4", "text": "#B5527A"},
    "Meta":       {"bg": "#EFF5FA", "text": "#2E6A9E"},
    "Cloudflare": {"bg": "#F5EDE5", "text": "#8B5E3C"},
    "AWS":        {"bg": "#F5EDE5", "text": "#8B5E3C"},
    "Dropbox":    {"bg": "#EFF5FA", "text": "#2E6A9E"},
    "Spotify":    {"bg": "#E8F2EC", "text": "#4A7C59"},
    "DoorDash":   {"bg": "#FDF0F4", "text": "#B5527A"},
    "Shopify":    {"bg": "#E8F2EC", "text": "#4A7C59"},
}
DEFAULT_STYLE = {"bg": "#E8F2EC", "text": "#4A7C59"}


def get_source_style(company):
    return SOURCE_STYLES.get(company, DEFAULT_STYLE)


def parse_tags(tags_str):
    try:
        return json.loads(tags_str) if tags_str else []
    except (json.JSONDecodeError, TypeError):
        return []


def parse_concepts(concepts_str):
    try:
        return json.loads(concepts_str) if concepts_str else []
    except (json.JSONDecodeError, TypeError):
        return []


@app.context_processor
def inject_helpers():
    bookmark_count = 0
    if current_user.is_authenticated:
        row = query_db(
            "SELECT COUNT(*) as c FROM user_bookmarks WHERE user_id = ?",
            (current_user.id,), one=True,
        )
        bookmark_count = row["c"] if row else 0
    return {
        "get_source_style": get_source_style,
        "parse_tags": parse_tags,
        "parse_concepts": parse_concepts,
        "bookmark_count": bookmark_count,
    }


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = User.get_by_username(username)
        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row["id"], row["username"]), remember=True)
            next_page = request.args.get("next") or url_for("home")
            return redirect(next_page)
        flash("Invalid username or password.")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not (3 <= len(username) <= 20):
            flash("Username must be 3–20 characters.")
        elif not username.isalnum():
            flash("Username may only contain letters and numbers.")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.")
        else:
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password, method="pbkdf2:sha256")),
                )
                db.commit()
                row = User.get_by_username(username)
                login_user(User(row["id"], row["username"]), remember=True)
                return redirect(url_for("home"))
            except sqlite3.IntegrityError:
                flash("That username is already taken.")
    return render_template("register.html")


@app.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── CLI ───────────────────────────────────────────────────────────────────────

@app.cli.command("create-user")
@click.argument("username")
def create_user_cmd(username):
    """Create a bootstrap user account."""
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password, method="pbkdf2:sha256")),
        )
        db.commit()
        click.echo(f"User '{username}' created.")
    except sqlite3.IntegrityError:
        click.echo(f"Error: username '{username}' already exists.", err=True)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    tag = request.args.get("tag")
    company = request.args.get("company")

    fetch_dates = query_db(
        "SELECT DISTINCT DATE(fetched_at) as fd FROM articles ORDER BY fd DESC LIMIT 2"
    )
    fetch_date_vals = [r["fd"] for r in fetch_dates]

    all_articles_tags = query_db("SELECT tags FROM articles")
    all_tags = set()
    for row in all_articles_tags:
        for t in parse_tags(row["tags"]):
            all_tags.add(t)
    all_tags = sorted(all_tags)

    all_companies = sorted([
        r["company"] for r in query_db("SELECT DISTINCT company FROM articles ORDER BY company")
    ])

    def _ordinal(d):
        n = d.day
        return f"{n}{'th' if 11<=n<=13 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')}"

    user_id = current_user.id if current_user.is_authenticated else None

    week_sections = []
    for fd in fetch_date_vals:
        where_conditions = ["DATE(a.fetched_at) = ?"]
        where_params = [fd]
        if tag:
            where_conditions.append("a.tags LIKE ?")
            where_params.append(f'%"{tag}"%')
        if company:
            where_conditions.append("a.company = ?")
            where_params.append(company)
        where = " AND ".join(where_conditions)

        if user_id:
            articles = query_db(
                f"""SELECT a.*,
                       CASE WHEN ub.article_id IS NOT NULL THEN 1 ELSE 0 END as is_bookmarked
                    FROM articles a
                    LEFT JOIN user_bookmarks ub ON ub.article_id = a.id AND ub.user_id = ?
                    WHERE {where}
                    ORDER BY a.company, a.title""",
                [user_id] + where_params,
            )
        else:
            articles = query_db(
                f"SELECT a.*, 0 as is_bookmarked FROM articles a WHERE {where} ORDER BY a.company, a.title",
                where_params,
            )

        fetch_date = datetime.strptime(fd, "%Y-%m-%d")
        week_sections.append({
            "label": f"Fetched {fetch_date.strftime('%B')} {_ordinal(fetch_date)}, {fetch_date.strftime('%Y')}",
            "articles": articles,
        })

    stats = {
        "new_this_week": query_db(
            "SELECT COUNT(*) as c FROM articles WHERE DATE(fetched_at) = ?",
            (fetch_date_vals[0],) if fetch_date_vals else ("",), one=True,
        )["c"],
        "sources": query_db("SELECT COUNT(DISTINCT company) as c FROM articles", one=True)["c"],
    }

    return render_template("home.html",
                           week_sections=week_sections,
                           all_tags=all_tags,
                           all_companies=all_companies,
                           active_tag=tag,
                           active_company=company,
                           stats=stats)


@app.route("/archives")
def archives():
    tag = request.args.get("tag")
    company = request.args.get("company")

    fetch_dates_all = query_db(
        "SELECT DISTINCT DATE(fetched_at) as fd FROM articles ORDER BY fd DESC"
    )
    all_fetch_dates = [r["fd"] for r in fetch_dates_all]
    archive_dates = all_fetch_dates[2:]

    all_articles_tags = query_db("SELECT tags FROM articles")
    all_tags = set()
    for row in all_articles_tags:
        for t in parse_tags(row["tags"]):
            all_tags.add(t)
    all_tags = sorted(all_tags)

    all_companies = sorted([
        r["company"] for r in query_db("SELECT DISTINCT company FROM articles ORDER BY company")
    ])

    def _ordinal(d):
        n = d.day
        return f"{n}{'th' if 11<=n<=13 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')}"

    week_data = []
    for fd in archive_dates:
        conditions = ["DATE(fetched_at) = ?"]
        params = [fd]
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        if company:
            conditions.append("company = ?")
            params.append(company)

        where = " AND ".join(conditions)
        articles = query_db(
            f"SELECT * FROM articles WHERE {where} ORDER BY company, title", params
        )

        if not articles:
            continue

        fetch_date = datetime.strptime(fd, "%Y-%m-%d")
        label = f"Fetched {fetch_date.strftime('%B')} {_ordinal(fetch_date)}, {fetch_date.strftime('%Y')}"
        week_data.append({
            "week_label": label,
            "count": len(articles),
            "articles": articles,
        })

    return render_template("archives.html",
                           weeks=week_data,
                           all_tags=all_tags,
                           all_companies=all_companies,
                           active_tag=tag,
                           active_company=company)


@app.route("/bookmarks")
@login_required
def bookmarks():
    articles = query_db("""
        SELECT a.*
        FROM articles a
        JOIN user_bookmarks ub ON ub.article_id = a.id
        WHERE ub.user_id = ?
        ORDER BY a.company, a.title
    """, (current_user.id,))
    return render_template("bookmarks.html", articles=articles)


@app.route("/notes")
@login_required
def notes():
    articles_with_notes = query_db("""
        SELECT a.id, a.title, a.company, a.url, n.id as note_id, n.content, n.updated_at
        FROM notes n JOIN articles a ON n.article_id = a.id
        WHERE n.user_id = ?
        ORDER BY n.updated_at DESC
    """, (current_user.id,))
    all_articles = query_db("SELECT id, title, company FROM articles ORDER BY company, title")

    selected_note = request.args.get("note_id")
    new_article_id = request.args.get("article_id")

    if new_article_id and not selected_note:
        existing = query_db(
            "SELECT id FROM notes WHERE article_id = ? AND user_id = ? ORDER BY updated_at DESC LIMIT 1",
            (new_article_id, current_user.id), one=True,
        )
        if existing:
            return redirect(f"/notes?note_id={existing['id']}")

    selected = None
    if selected_note:
        selected = query_db("""
            SELECT n.*, a.title as article_title, a.company, a.url
            FROM notes n JOIN articles a ON n.article_id = a.id
            WHERE n.id = ? AND n.user_id = ?
        """, (selected_note, current_user.id), one=True)

    return render_template("notes.html",
                           notes_list=articles_with_notes,
                           all_articles=all_articles,
                           selected=selected,
                           new_article_id=new_article_id)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        fts_query = " OR ".join(f'{word}*' for word in q.split())
        results = query_db("""
            SELECT a.id, a.title, a.url, a.company, a.tags,
                   a.ai_problem, a.summary, a.week_label,
                   snippet(articles_fts, 0, '<mark>', '</mark>', '...', 20) as snip_title,
                   snippet(articles_fts, 1, '<mark>', '</mark>', '...', 30) as snip_summary,
                   snippet(articles_fts, 2, '<mark>', '</mark>', '...', 30) as snip_ai
            FROM articles_fts
            JOIN articles a ON articles_fts.rowid = a.rowid
            WHERE articles_fts MATCH ?
            ORDER BY rank
            LIMIT 30
        """, (fts_query,))
    return render_template("search.html", results=results, query=q)


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/bookmark", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def toggle_bookmark():
    data = request.get_json()
    article_id = data.get("article_id")
    if not article_id:
        return jsonify({"error": "article_id required"}), 400

    db = get_db()
    if not db.execute("SELECT id FROM articles WHERE id = ?", (article_id,)).fetchone():
        return jsonify({"error": "not found"}), 404

    existing = db.execute(
        "SELECT 1 FROM user_bookmarks WHERE user_id = ? AND article_id = ?",
        (current_user.id, article_id),
    ).fetchone()

    if existing:
        db.execute("DELETE FROM user_bookmarks WHERE user_id = ? AND article_id = ?",
                   (current_user.id, article_id))
        bookmarked = False
    else:
        db.execute("INSERT INTO user_bookmarks (user_id, article_id) VALUES (?, ?)",
                   (current_user.id, article_id))
        bookmarked = True
    db.commit()

    count = db.execute(
        "SELECT COUNT(*) as c FROM user_bookmarks WHERE user_id = ?", (current_user.id,)
    ).fetchone()["c"]
    return jsonify({"bookmarked": bookmarked, "total_bookmarks": count})


@app.route("/api/notes", methods=["POST"])
@login_required
@limiter.limit("20 per minute")
def save_note():
    data = request.get_json()
    article_id = data.get("article_id")
    note_id = data.get("note_id")
    raw = data.get("content")
    if raw is None:
        content = ""
    elif isinstance(raw, str):
        content = raw
    else:
        content = str(raw)

    db = get_db()
    now = datetime.utcnow().isoformat()

    if note_id:
        old_row = db.execute(
            "SELECT content FROM notes WHERE id = ? AND user_id = ?",
            (note_id, current_user.id),
        ).fetchone()
        if not old_row:
            return jsonify({"error": "note not found"}), 404
        old_content = old_row["content"] or ""
        db.execute(
            "UPDATE notes SET content = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (content, now, note_id, current_user.id),
        )
        try:
            db.execute("INSERT INTO notes_fts(notes_fts, rowid, content) VALUES('delete', ?, ?)",
                       (note_id, old_content))
        except Exception:
            pass
        db.execute("INSERT INTO notes_fts(rowid, content) VALUES(?, ?)", (note_id, content))
    else:
        if not article_id:
            return jsonify({"error": "article_id required"}), 400
        if not content.strip():
            return jsonify({"error": "content required for new notes"}), 400
        cur = db.execute(
            "INSERT INTO notes (article_id, content, created_at, updated_at, user_id) VALUES (?, ?, ?, ?, ?)",
            (article_id, content, now, now, current_user.id),
        )
        new_id = cur.lastrowid
        db.execute("INSERT INTO notes_fts(rowid, content) VALUES(?, ?)", (new_id, content))

    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
@login_required
@limiter.limit("20 per minute")
def delete_note(note_id):
    db = get_db()
    note = db.execute(
        "SELECT content FROM notes WHERE id = ? AND user_id = ?",
        (note_id, current_user.id),
    ).fetchone()
    if not note:
        return jsonify({"error": "not found"}), 404
    db.execute("INSERT INTO notes_fts(notes_fts, rowid, content) VALUES('delete', ?, ?)",
               (note_id, note["content"]))
    db.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, current_user.id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notes/search")
@login_required
def search_notes():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    fts_query = " OR ".join(f'{word}*' for word in q.split())
    results = query_db("""
        SELECT n.id as note_id, n.content, n.article_id, n.updated_at,
               a.title, a.company, a.url,
               snippet(notes_fts, 0, '<mark>', '</mark>', '...', 20) as snippet
        FROM notes_fts
        JOIN notes n ON notes_fts.rowid = n.id
        JOIN articles a ON n.article_id = a.id
        WHERE notes_fts MATCH ? AND n.user_id = ?
        ORDER BY rank
        LIMIT 20
    """, (fts_query, current_user.id))

    return jsonify([dict(r) for r in results])


# ── Health check ──────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    try:
        article_count = query_db("SELECT COUNT(*) as c FROM articles", one=True)["c"]
        return jsonify({
            "status": "ok",
            "articles": article_count,
            "timestamp": datetime.utcnow().isoformat(),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(429)
def rate_limited(e):
    return jsonify({"error": "Too many requests. Please slow down."}), 429


@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run(debug=True, port=5001)
