#!/usr/bin/env python3
"""
Distributed Readings — Flask web app.
Serves the Botanical Morning-themed website for browsing tech blog articles.

Run locally: python3 web/app.py
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(PROJECT_ROOT, "data", "techblogs.db")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # 64KB max request body

# Rate limiter — keyed by IP address
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],  # No global limit — only apply per-route
    storage_uri="memory://",
)


# ── Database helpers ──────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        _ensure_fts_tables(g.db)
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

    # Check if FTS data table is effectively empty (≤2 rows = just root node metadata)
    # For FTS5 content tables, COUNT(*) reads from the content table so can't use it.
    # articles_fts_data holds the actual inverted index B-tree nodes.
    fts_data_rows = db.execute("SELECT COUNT(*) FROM articles_fts_data").fetchone()[0]
    if fts_data_rows <= 2:
        art_count = db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if art_count > 0:
            # 'rebuild' reads from the content table (articles) and rebuilds the full index
            db.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
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


def get_greeting():
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    elif hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"


def parse_tags(tags_str):
    """Parse JSON tags string to a list."""
    try:
        return json.loads(tags_str) if tags_str else []
    except (json.JSONDecodeError, TypeError):
        return []


def parse_concepts(concepts_str):
    """Parse JSON concepts string to a list."""
    try:
        return json.loads(concepts_str) if concepts_str else []
    except (json.JSONDecodeError, TypeError):
        return []


# Make helpers available in all templates
@app.context_processor
def inject_helpers():
    bookmark_count = query_db("SELECT COUNT(*) as c FROM articles WHERE bookmarked = 1", one=True)["c"]
    return {
        "get_source_style": get_source_style,
        "parse_tags": parse_tags,
        "parse_concepts": parse_concepts,
        "greeting": get_greeting(),
        "bookmark_count": bookmark_count,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    tag = request.args.get("tag")
    company = request.args.get("company")

    # Get latest 2 weeks
    weeks = query_db(
        "SELECT DISTINCT week_label FROM articles WHERE week_label != '' ORDER BY week_label DESC LIMIT 2"
    )
    week_labels = [w["week_label"] for w in weeks]

    # Get all unique tags
    all_articles_tags = query_db("SELECT tags FROM articles")
    all_tags = set()
    for row in all_articles_tags:
        for t in parse_tags(row["tags"]):
            all_tags.add(t)
    all_tags = sorted(all_tags)

    # Get all unique companies
    all_companies = sorted([r["company"] for r in query_db("SELECT DISTINCT company FROM articles ORDER BY company")])

    # Build week sections with articles
    week_sections = []
    for i, wl in enumerate(week_labels):
        conditions = ["week_label = ?"]
        params = [wl]
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

        # Get actual fetch date from the articles themselves
        fetch_row = query_db(
            "SELECT MAX(fetched_at) as latest_fetch FROM articles WHERE week_label = ?",
            (wl,), one=True
        )
        if fetch_row and fetch_row["latest_fetch"]:
            fetch_date = datetime.strptime(fetch_row["latest_fetch"][:10], "%Y-%m-%d")
        else:
            fetch_date = datetime.strptime(f"{wl}-1", "%G-W%V-%u")

        def _ordinal(d):
            n = d.day
            return f"{n}{'th' if 11<=n<=13 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')}"

        week_sections.append({
            "label": f"Fetched {fetch_date.strftime('%B')} {_ordinal(fetch_date)}, {fetch_date.strftime('%Y')}",
            "articles": articles,
        })

    # Stats
    stats = {
        "new_this_week": query_db(
            "SELECT COUNT(*) as c FROM articles WHERE week_label = ?",
            (week_labels[0],) if week_labels else ("",), one=True
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

    # Skip the latest 2 weeks (already shown on home page)
    weeks = query_db(
        "SELECT DISTINCT week_label FROM articles WHERE week_label != '' ORDER BY week_label DESC LIMIT -1 OFFSET 2"
    )

    all_articles_tags = query_db("SELECT tags FROM articles")
    all_tags = set()
    for row in all_articles_tags:
        for t in parse_tags(row["tags"]):
            all_tags.add(t)
    all_tags = sorted(all_tags)

    all_companies = sorted([r["company"] for r in query_db("SELECT DISTINCT company FROM articles ORDER BY company")])

    week_data = []
    for w in weeks:
        wl = w["week_label"]
        conditions = ["week_label = ?"]
        params = [wl]
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

        # Show publication week range (Mon – Sun) derived from ISO week label
        week_start = datetime.strptime(f"{wl}-1", "%G-W%V-%u")
        week_end = week_start + timedelta(days=6)

        # Format: "Mar 30 – Apr 05, 2026"
        if week_start.month == week_end.month:
            label = f"{week_start.strftime('%b %d')} – {week_end.strftime('%d, %Y')}"
        else:
            label = f"{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}"

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
def bookmarks():
    articles = query_db("SELECT * FROM articles WHERE bookmarked = 1 ORDER BY company, title")
    return render_template("bookmarks.html", articles=articles)


@app.route("/notes")
def notes():
    # Get articles that have notes
    articles_with_notes = query_db("""
        SELECT a.id, a.title, a.company, a.url, n.id as note_id, n.content, n.updated_at
        FROM notes n JOIN articles a ON n.article_id = a.id
        ORDER BY n.updated_at DESC
    """)
    # Get all articles for the "new note" dropdown
    all_articles = query_db("SELECT id, title, company FROM articles ORDER BY company, title")

    selected_note = request.args.get("note_id")
    new_article_id = request.args.get("article_id")  # pre-select article for new note

    # If arriving from an article card and a note already exists, open that note
    if new_article_id and not selected_note:
        existing = query_db(
            "SELECT id FROM notes WHERE article_id = ? ORDER BY updated_at DESC LIMIT 1",
            (new_article_id,), one=True
        )
        if existing:
            return redirect(f"/notes?note_id={existing['id']}")

    selected = None
    if selected_note:
        selected = query_db("""
            SELECT n.*, a.title as article_title, a.company, a.url
            FROM notes n JOIN articles a ON n.article_id = a.id
            WHERE n.id = ?
        """, (selected_note,), one=True)

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
@limiter.limit("30 per minute")
def toggle_bookmark():
    data = request.get_json()
    article_id = data.get("article_id")
    if not article_id:
        return jsonify({"error": "article_id required"}), 400

    db = get_db()
    article = db.execute("SELECT bookmarked FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not article:
        return jsonify({"error": "not found"}), 404

    new_val = 0 if article["bookmarked"] else 1
    db.execute("UPDATE articles SET bookmarked = ? WHERE id = ?", (new_val, article_id))
    db.commit()

    count = db.execute("SELECT COUNT(*) as c FROM articles WHERE bookmarked = 1").fetchone()["c"]
    return jsonify({"bookmarked": bool(new_val), "total_bookmarks": count})


@app.route("/api/notes", methods=["POST"])
@limiter.limit("20 per minute")
def save_note():
    data = request.get_json()
    article_id = data.get("article_id")
    content = data.get("content", "").strip()
    note_id = data.get("note_id")

    if not article_id or not content:
        return jsonify({"error": "article_id and content required"}), 400

    db = get_db()
    now = datetime.utcnow().isoformat()

    if note_id:
        db.execute("UPDATE notes SET content = ?, updated_at = ? WHERE id = ?",
                   (content, now, note_id))
        # Sync FTS5 index — delete old entry, insert updated content
        db.execute("INSERT INTO notes_fts(notes_fts, rowid, content) VALUES('delete', ?, ?)",
                   (note_id, content))
        db.execute("INSERT INTO notes_fts(rowid, content) VALUES(?, ?)", (note_id, content))
    else:
        cur = db.execute(
            "INSERT INTO notes (article_id, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (article_id, content, now, now)
        )
        new_id = cur.lastrowid
        # Add to FTS5 index
        db.execute("INSERT INTO notes_fts(rowid, content) VALUES(?, ?)", (new_id, content))

    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
@limiter.limit("20 per minute")
def delete_note(note_id):
    db = get_db()
    # Remove from FTS5 index before deleting the row
    note = db.execute("SELECT content FROM notes WHERE id = ?", (note_id,)).fetchone()
    if note:
        db.execute("INSERT INTO notes_fts(notes_fts, rowid, content) VALUES('delete', ?, ?)",
                   (note_id, note["content"]))
    db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notes/search")
def search_notes():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])

    # FTS5 MATCH with prefix search (append * for partial matching)
    fts_query = " OR ".join(f'{word}*' for word in q.split())
    results = query_db("""
        SELECT n.id as note_id, n.content, n.article_id, n.updated_at,
               a.title, a.company, a.url,
               snippet(notes_fts, 0, '<mark>', '</mark>', '...', 20) as snippet
        FROM notes_fts
        JOIN notes n ON notes_fts.rowid = n.id
        JOIN articles a ON n.article_id = a.id
        WHERE notes_fts MATCH ?
        ORDER BY rank
        LIMIT 20
    """, (fts_query,))

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
