"""
One-time fix: recalculate week_label from published date instead of fetched_at.
Run once on EC2: python3 scripts/fix_week_labels.py
"""
import sqlite3
import os
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "techblogs.db")

conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT id, published, fetched_at, week_label FROM articles").fetchall()

fixed = 0
for row in rows:
    published = row["published"] or ""
    if not published:
        continue

    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        correct_label = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
    except (ValueError, TypeError):
        continue

    if correct_label != row["week_label"]:
        conn.execute("UPDATE articles SET week_label = ? WHERE id = ?", (correct_label, row["id"]))
        print(f"  Fixed: {row['id'][:8]}... {row['week_label']} → {correct_label}")
        fixed += 1

conn.commit()
conn.close()
print(f"\nDone. Fixed {fixed} articles.")
