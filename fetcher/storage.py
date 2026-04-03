# fetcher/storage.py
#
# WHY THIS FILE EXISTS:
# Every subsystem needs to read and write articles. If each subsystem implements
# its own persistence, you end up with subtle bugs when the format changes.
# This is the Single Responsibility Principle: ONE place manages persistence.
#
# WHY SQLite (not JSON)?
# JSON was great for learning — you could open articles.json in VS Code and see
# what was stored. But once we added a web frontend, we needed queries, indexes,
# and concurrent reads. SQLite gives us all of that in a single file, no server.
#
# PRODUCTION EVOLUTION PATH:
# JSON -> SQLite (current) -> Postgres (when you need concurrent writes)

import json
import os
import sqlite3
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(PROJECT_ROOT, "data", "techblogs.db")


def _get_conn() -> sqlite3.Connection:
    """Get a connection to the SQLite database, creating tables if needed."""
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent read performance
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn):
    """Create tables if they don't exist yet (first run)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id          TEXT PRIMARY KEY,
            url         TEXT UNIQUE NOT NULL,
            title       TEXT NOT NULL,
            summary     TEXT DEFAULT '',
            company     TEXT NOT NULL,
            blog_name   TEXT NOT NULL,
            tags        TEXT NOT NULL DEFAULT '[]',
            tags_hint   TEXT DEFAULT '[]',
            published   TEXT DEFAULT '',
            fetched_at  TEXT NOT NULL,
            status      TEXT DEFAULT 'new',
            ai_problem  TEXT,
            ai_solution TEXT,
            ai_concepts TEXT,
            ai_tagged_at TEXT,
            week_label  TEXT,
            bookmarked  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id  TEXT NOT NULL REFERENCES articles(id),
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_articles_week ON articles(week_label);
        CREATE INDEX IF NOT EXISTS idx_articles_company ON articles(company);
        CREATE INDEX IF NOT EXISTS idx_articles_bookmarked ON articles(bookmarked);
        CREATE INDEX IF NOT EXISTS idx_notes_article ON notes(article_id);
    """)


def _get_week_label(date_str: str) -> str:
    """Convert an ISO date string to a week label like '2026-W14'."""
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
    except (ValueError, TypeError):
        return ""


def add_articles(new_articles: list[dict]) -> dict:
    """
    Add new articles to the store, skipping duplicates by URL.
    Returns a summary dict: { added: int, skipped: int, total: int }
    """
    conn = _get_conn()
    added = 0
    skipped = 0

    for a in new_articles:
        week_label = _get_week_label(a.get("fetched_at", "")) or _get_week_label(a.get("published", ""))
        try:
            conn.execute("""
                INSERT INTO articles
                (id, url, title, summary, company, blog_name, tags, tags_hint,
                 published, fetched_at, status, week_label, bookmarked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                a["id"],
                a["url"],
                a["title"],
                a.get("summary", ""),
                a["company"],
                a.get("blog_name", ""),
                json.dumps(a.get("tags", [])),
                json.dumps(a.get("tags_hint", [])),
                a.get("published", ""),
                a.get("fetched_at", ""),
                a.get("status", "new"),
                week_label,
            ))
            added += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()
    return {"added": added, "skipped": skipped, "total": total}


def get_articles(
    topic: str = "all",
    company: str = "all",
    status: str = "all",
    limit: int = None
) -> list[dict]:
    """
    Retrieve articles with optional filters.
    Returns list of dicts matching the original article schema.
    """
    conn = _get_conn()
    conditions = []
    params = []

    if topic != "all":
        conditions.append("tags LIKE ?")
        params.append(f'%"{topic}"%')

    if company != "all":
        conditions.append("company = ?")
        params.append(company)

    if status != "all":
        conditions.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order = "ORDER BY fetched_at DESC"
    limit_clause = f"LIMIT {limit}" if limit else ""

    rows = conn.execute(
        f"SELECT * FROM articles {where} {order} {limit_clause}", params
    ).fetchall()
    conn.close()

    # Convert rows to dicts matching the schema other subsystems expect
    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a SQLite Row to the article dict format used by other subsystems."""
    d = dict(row)
    # Parse JSON fields back to lists
    d["tags"] = json.loads(d["tags"]) if d["tags"] else []
    d["tags_hint"] = json.loads(d["tags_hint"]) if d["tags_hint"] else []

    # Reconstruct ai_summary dict if AI fields are populated
    if d.get("ai_problem") and d["ai_problem"] != "Could not parse AI response.":
        d["ai_summary"] = {
            "problem": d.get("ai_problem", ""),
            "solution": d.get("ai_solution", ""),
            "concepts": json.loads(d["ai_concepts"]) if d.get("ai_concepts") else [],
            "study_summary": "",
        }

    return d


def update_article_ai_analysis(url: str, analysis: dict) -> bool:
    """
    Persist AI analysis results for one article.
    Updates ai_problem, ai_solution, ai_concepts, tags, and ai_tagged_at.

    Returns True if found and updated, False if URL not in store.
    """
    conn = _get_conn()
    ai = analysis.get("ai_summary", {})
    tags = analysis.get("tags", [])

    result = conn.execute("""
        UPDATE articles SET
            ai_problem = ?,
            ai_solution = ?,
            ai_concepts = ?,
            tags = ?,
            ai_tagged_at = ?
        WHERE url = ?
    """, (
        ai.get("problem", ""),
        ai.get("solution", ""),
        json.dumps(ai.get("concepts", [])),
        json.dumps(tags),
        datetime.utcnow().isoformat(),
        url,
    ))
    conn.commit()
    updated = result.rowcount > 0
    conn.close()
    return updated


def update_article_status(url: str, status: str) -> bool:
    """Update the study status of an article (new / in-progress / done)."""
    conn = _get_conn()
    result = conn.execute("""
        UPDATE articles SET status = ?, fetched_at = ? WHERE url = ?
    """, (status, datetime.utcnow().isoformat(), url))
    conn.commit()
    updated = result.rowcount > 0
    conn.close()
    return updated
