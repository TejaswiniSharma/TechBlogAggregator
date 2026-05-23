#!/usr/bin/env python3
"""
Smoke test for POST /api/internal/ai-tag.

Simulates what the Lambda will eventually do: sign a JSON body with HMAC-SHA256
using the shared secret, POST to Flask, verify the response.

Usage:
    export INTERNAL_SHARED_SECRET="some-long-random-string"
    python3 scripts/test_internal_ai_tag.py                  # success callback
    python3 scripts/test_internal_ai_tag.py --bad-sig        # bad signature → 401
    python3 scripts/test_internal_ai_tag.py --missing-id     # missing article_id → 400
    python3 scripts/test_internal_ai_tag.py --failure        # failure callback
    python3 scripts/test_internal_ai_tag.py --article-id <id>  # specific article

Make sure Flask is running with the same INTERNAL_SHARED_SECRET env var.
"""
import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import urllib.request


URL = "http://localhost:5001/api/internal/ai-tag"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "techblogs.db")


def pick_pending_article_id() -> str:
    """Grab any article with ai_status='pending' so the test exercises a real write."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT id FROM articles WHERE ai_status = 'pending' LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        sys.exit("No pending articles to test against — fetch first or pass --article-id")
    return row[0]


def post_signed(body: dict, secret: str, sig_override: str = None):
    body_bytes = json.dumps(body).encode()
    sig = sig_override or hmac.new(
        secret.encode(), body_bytes, hashlib.sha256
    ).hexdigest()
    req = urllib.request.Request(
        URL,
        data=body_bytes,
        headers={"Content-Type": "application/json", "X-Signature": sig},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bad-sig", action="store_true")
    p.add_argument("--missing-id", action="store_true")
    p.add_argument("--failure", action="store_true")
    p.add_argument("--article-id", default=None)
    args = p.parse_args()

    secret = os.environ.get("INTERNAL_SHARED_SECRET")
    if not secret:
        sys.exit("Set INTERNAL_SHARED_SECRET first. Example:\n  "
                 "export INTERNAL_SHARED_SECRET='dev-only-not-real-prod-key'")

    article_id = args.article_id or pick_pending_article_id()

    if args.missing_id:
        body = {"ai_problem": "x", "ai_solution": "y", "ai_concepts": [], "tags": []}
    elif args.failure:
        body = {"article_id": article_id, "error": "Claude returned 500"}
    else:
        body = {
            "article_id": article_id,
            "ai_problem": "Test problem — how do we handle X at scale?",
            "ai_solution": "Test solution — we used Y and Z to solve it.",
            "ai_concepts": ["test-concept-1", "test-concept-2"],
            "tags": ["distributed-systems", "test"],
        }

    sig_override = "deadbeef" * 8 if args.bad_sig else None
    status, response = post_signed(body, secret, sig_override)
    print(f"→ POST {URL}")
    print(f"→ Body: {json.dumps(body)[:120]}")
    print(f"← {status} {response}")


if __name__ == "__main__":
    main()
