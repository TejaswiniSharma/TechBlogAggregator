#!/usr/bin/env python3
"""
Local invocation harness — runs the Lambda handler against the local Flask
without involving AWS. Picks a real pending article from SQLite, fakes an
SQS event around it, and invokes lambda_handler().

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    export INTERNAL_SHARED_SECRET="dev-only-test-key-not-for-prod"
    export CALLBACK_URL="http://localhost:5001/api/internal/ai-tag"

    python3 lambda/ai_tagger/test_local.py                 # latest pending article
    python3 lambda/ai_tagger/test_local.py --article-id X  # specific article
    python3 lambda/ai_tagger/test_local.py --dry-run       # skip Claude, fake response
"""
import argparse
import json
import os
import sqlite3
import sys

# Make handler.py importable when running from project root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import handler  # noqa: E402

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB = os.path.join(PROJECT_ROOT, "data", "techblogs.db")


def fetch_article(article_id: str | None) -> dict:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    if article_id:
        row = conn.execute(
            "SELECT id, title, summary, company, tags_hint, url "
            "FROM articles WHERE id = ?",
            (article_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, title, summary, company, tags_hint, url FROM articles "
            "WHERE ai_status = 'pending' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
    conn.close()
    if not row:
        sys.exit("No matching article in DB (try fetching first or passing --article-id)")
    return {
        "article_id": row["id"],
        "title": row["title"],
        "summary": row["summary"] or "",
        "company": row["company"],
        "tags_hint": json.loads(row["tags_hint"] or "[]"),
        "url": row["url"],
    }


def build_sqs_event(article_body: dict) -> dict:
    """Minimal shape of what AWS sends to a Lambda triggered by SQS."""
    return {
        "Records": [
            {
                "messageId": "local-test-msg-1",
                "receiptHandle": "local-receipt",
                "body": json.dumps(article_body),
                "attributes": {"ApproximateReceiveCount": "1"},
                "eventSource": "aws:sqs",
            }
        ]
    }


def monkeypatch_claude_with_mock():
    """Replace _ask_claude with a stub so we can test wiring without API cost."""
    def fake(article):
        return {
            "problem": f"[MOCK] What is the engineering challenge in {article.get('title', '')[:40]}?",
            "solution": "[MOCK] They solved it by using fake-mock-pattern-X.",
            "concepts": ["mock-concept-a", "mock-concept-b"],
            "tags": ["distributed-systems", "general"],
        }
    handler._ask_claude = fake
    print("(--dry-run: Claude call mocked)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--article-id", default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="Skip the Claude call and use a fake response.")
    args = p.parse_args()

    required = ["INTERNAL_SHARED_SECRET", "CALLBACK_URL"]
    if not args.dry_run:
        required.append("ANTHROPIC_API_KEY")
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")

    if args.dry_run:
        # handler._validate_env() requires ANTHROPIC_API_KEY at handler entry, but
        # --dry-run replaces _ask_claude before it's ever called. Provide a dummy.
        os.environ.setdefault("ANTHROPIC_API_KEY", "dummy-for-dry-run-only")
        monkeypatch_claude_with_mock()

    article = fetch_article(args.article_id)
    print(f"→ Article: {article['title'][:80]}")
    print(f"→ Company: {article['company']}")
    print(f"→ id: {article['article_id']}")

    event = build_sqs_event(article)
    result = handler.lambda_handler(event, context=None)
    print(f"← Handler result: {json.dumps(result)}")

    if result["batchItemFailures"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
