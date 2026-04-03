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
from flask import Flask, render_template, request, jsonify, g

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(PROJECT_ROOT, "data", "techblogs.db")

app = Flask(__name__, template_folder="templates", static_folder="static")


# ── Database helpers ──────────────────────────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
        g.db.row_factory = sqlite3.Row
    return g.db


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

    # Build week sections with articles
    week_sections = []
    for i, wl in enumerate(week_labels):
        if tag:
            articles = query_db(
                "SELECT * FROM articles WHERE week_label = ? AND tags LIKE ? ORDER BY company, title",
                (wl, f'%"{tag}"%')
            )
        else:
            articles = query_db(
                "SELECT * FROM articles WHERE week_label = ? ORDER BY company, title",
                (wl,)
            )

        # Parse week label to date range (ISO week: Monday–Sunday)
        week_start = datetime.strptime(f"{wl}-1", "%G-W%V-%u")
        week_end = week_start + timedelta(days=6)

        week_sections.append({
            "label": "Current Week" if i == 0 else "Previous Week",
            "date_range": f"{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}",
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
                           active_tag=tag,
                           stats=stats)


@app.route("/archives")
def archives():
    tag = request.args.get("tag")

    weeks = query_db(
        "SELECT DISTINCT week_label FROM articles WHERE week_label != '' ORDER BY week_label DESC"
    )

    all_articles_tags = query_db("SELECT tags FROM articles")
    all_tags = set()
    for row in all_articles_tags:
        for t in parse_tags(row["tags"]):
            all_tags.add(t)
    all_tags = sorted(all_tags)

    week_data = []
    for w in weeks:
        wl = w["week_label"]
        if tag:
            articles = query_db(
                "SELECT * FROM articles WHERE week_label = ? AND tags LIKE ? ORDER BY company, title",
                (wl, f'%"{tag}"%')
            )
        else:
            articles = query_db(
                "SELECT * FROM articles WHERE week_label = ? ORDER BY company, title",
                (wl,)
            )

        if not articles:
            continue

        week_start = datetime.strptime(f"{wl}-1", "%G-W%V-%u")
        week_end = week_start + timedelta(days=6)

        week_data.append({
            "week_label": wl,
            "date_range": f"{week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}",
            "count": len(articles),
            "articles": articles,
        })

    return render_template("archives.html",
                           weeks=week_data,
                           all_tags=all_tags,
                           active_tag=tag)


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
                           selected=selected)


@app.route("/about")
def about():
    return render_template("about.html")


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/bookmark", methods=["POST"])
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
    else:
        db.execute("INSERT INTO notes (article_id, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
                   (article_id, content, now, now))

    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    db = get_db()
    db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    db.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
