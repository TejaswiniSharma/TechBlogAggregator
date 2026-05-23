# lambda/ai_tagger/handler.py
#
# WHY THIS FILE EXISTS:
# This is the worker side of the AI-tagging pipeline. The synchronous tagger
# in ai_tagger/claude_tagger.py blocks the EC2 cron run on every Claude call.
# Moving it to Lambda + SQS means:
#   - the fetcher returns instantly after writing to SQLite
#   - Claude calls happen in parallel (Lambda fans out)
#   - retries are free (SQS handles them)
#   - one bad article can't poison the batch (per-message isolation)
#
# DESIGN DECISIONS:
# - Self-contained: doesn't import project modules. Lambda packages stay small
#   and portable. The Claude prompt is duplicated from ai_tagger/claude_tagger.py
#   — a tolerable cost; a test pinning the prompt would catch drift.
# - urllib (not requests) for the callback: stdlib only → no extra dependency
#   in the deployment zip.
# - Env vars for config: the simplest contract. Migrate to Secrets Manager
#   in Phase 5 (hardening) when ANTHROPIC_API_KEY rotation matters.
# - Partial batch failure: returns `batchItemFailures` so SQS retries only
#   the records that raised, not the successful ones.
#
# FAILURE-CLASSIFICATION RULES (the heart of the design):
#   Transient (raise → SQS retries → eventually DLQ + alarm):
#     - Claude 5xx
#     - Callback 5xx
#     - Network errors (URLError)
#   Permanent (POST failure callback, return normally so SQS deletes the msg):
#     - Claude returns unparseable / empty / non-text response
#     - Claude 4xx (bad prompt, content policy, etc.)
#     - Callback 4xx (article deleted, signature rejected, etc.) — already
#       posted, nothing more we can do
#     - Malformed SQS message (no article_id) — log and ack; we can't even
#       send a failure callback without an article_id
#   Hard config bug (raise out of lambda_handler → invocation fails):
#     - Required env var missing — fail every invocation loudly until fixed
#
# LAMBDA RUNTIME REQUIREMENTS:
#   - Timeout: ≥ 30s. Claude Haiku replies in 5–15s; callback timeout is 10s;
#     buffer for cold start + retries.
#   - Memory: 512 MB is fine.
#   - Trigger: SQS event source mapping with ReportBatchItemFailures: true.

import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request

import anthropic

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# Required env vars — checked at every invocation entry (see _validate_env).
#   ANTHROPIC_API_KEY      — Claude API key
#   CALLBACK_URL           — e.g. https://distributedreadings.uk/api/internal/ai-tag
#   INTERNAL_SHARED_SECRET — HMAC secret, must match Flask's value
_REQUIRED_ENV = ("ANTHROPIC_API_KEY", "CALLBACK_URL", "INTERNAL_SHARED_SECRET")


class ClaudeResponseError(Exception):
    """Permanent failure from Claude: empty content, non-text block, or unparseable JSON."""


# Module-level client reused across warm invocations. Cold starts pay the
# HTTP-connection-pool warmup once; subsequent invocations reuse it.
_anthropic_client: anthropic.Anthropic | None = None


def _client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


def _validate_env() -> None:
    """
    Verify required env vars are set. Raises EnvironmentError on first invocation
    if any are missing — this fails the Lambda invocation loudly (no batchItemFailures
    returned, so SQS keeps the messages and retries until DLQ, and the Lambda
    error metric fires whatever CloudWatch alarm you've wired up).

    Better to alarm immediately on a config bug than silently process forever.
    """
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(
            f"Missing required env vars: {', '.join(missing)}. "
            "Set them on the Lambda function (or in your shell for local tests)."
        )


# Same prompt as ai_tagger/claude_tagger.py — kept inline so the Lambda
# package has no project-module imports.
_PROMPT = """You are analyzing a tech engineering blog post for a software engineer studying system design for interviews.

Company: {company}
Known focus areas: {tags_hint}

Article title: {title}

Article summary:
{summary}

Extract the following and respond with ONLY valid JSON — no markdown, no explanation, just the JSON object:

{{
  "problem": "One sentence: what specific engineering problem was this company solving?",
  "solution": "Two to three sentences: how did they solve it? Focus on the technical approach.",
  "concepts": ["list", "of", "system design concepts", "this article teaches"],
  "tags": ["list", "of", "relevant topic tags", "from this set only: caching, rate-limiting, distributed-systems, databases, messaging-queues, microservices, load-balancing, observability, ml-systems, search, real-time-systems, storage-systems, api-design, security, chaos-engineering, general"]
}}

Rules:
- Be specific to THIS article, not generic advice.
- concepts should be concrete terms (e.g. "write-ahead log", "consistent hashing") not vague labels.
- tags must only use values from the allowed set above.
"""


def _ask_claude(article: dict) -> dict:
    """
    Call Claude and return the parsed JSON response.

    Raises:
        ClaudeResponseError       — empty/non-text/unparseable response (permanent)
        anthropic.APIStatusError  — 4xx (caller treats as permanent) or 5xx (transient)
        Any other exception        — treated as transient by the caller
    """
    summary = article.get("summary") or "(No summary available; analyze based on the title alone.)"
    prompt = _PROMPT.format(
        company=article.get("company", "Unknown"),
        tags_hint=", ".join(article.get("tags_hint", [])) or "general engineering",
        title=article.get("title", ""),
        summary=summary,
    )
    response = _client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    # Guard against empty or non-text content blocks — both would have raised
    # IndexError/AttributeError on the next line, which would be caught as
    # transient and retried forever.
    if not response.content:
        raise ClaudeResponseError("empty response content")
    first = response.content[0]
    if not hasattr(first, "text"):
        raise ClaudeResponseError(f"non-text response block: {type(first).__name__}")

    raw = first.text.strip()
    # Strip ```json fences if Claude wraps the JSON despite our instruction.
    if raw.startswith("```"):
        raw = "\n".join(l for l in raw.split("\n") if not l.strip().startswith("```")).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # Truncate raw text to avoid logging huge model outputs.
        raise ClaudeResponseError(f"json parse failed: {str(e)[:120]}") from e


def _post_callback(payload: dict) -> int:
    """
    POST signed payload to Flask. Returns the HTTP status code.

    Raises:
        urllib.error.HTTPError  — only on 5xx (transient; caller will let SQS retry)
        urllib.error.URLError   — network/DNS/timeout (transient)
    Returns:
        int status code in [200, 500). 4xx is returned (not raised) so the
        caller can classify it as permanent.

    The body is canonically serialized (sort_keys + compact separators) so a
    re-serializing proxy can't silently invalidate the HMAC. Flask compares
    the signature against the raw bytes it receives, so this is belt-and-
    suspenders, but cheap.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(
        os.environ["INTERNAL_SHARED_SECRET"].encode(), body, hashlib.sha256
    ).hexdigest()
    req = urllib.request.Request(
        os.environ["CALLBACK_URL"],
        data=body,
        headers={"Content-Type": "application/json", "X-Signature": sig},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            raise  # transient — SQS will retry
        # 4xx: caller decides. We've already POSTed; retrying won't fix
        # a permanent rejection (sig mismatch, deleted article, validation).
        return e.code


def _safe_failure_callback(article_id: str, error: str) -> None:
    """
    Best-effort failure callback for permanent errors.

    Swallows BOTH 4xx (callback rejected the failure too — nothing to do)
    and 5xx/network (Flask is down — we'd rather lose the failure
    notification than convert a permanent error into infinite SQS retries).
    """
    try:
        status = _post_callback({"article_id": article_id, "error": error[:200]})
        if status >= 400:
            logger.warning(f"Failure callback returned {status} for {article_id}")
    except Exception as e:
        logger.warning(f"Failure callback unreachable for {article_id}: {e}")


def _process_record(sqs_record: dict) -> None:
    """
    Process one SQS message. See FAILURE-CLASSIFICATION RULES at the top of
    this file for the contract.
    """
    body = json.loads(sqs_record["body"])
    article_id = body.get("article_id")
    if not article_id:
        # Malformed message — can't send a failure callback without an id.
        # Log loudly and acknowledge so we don't loop forever.
        logger.error(
            f"SQS message missing article_id (acking): messageId={sqs_record.get('messageId')}"
        )
        return

    title = (body.get("title") or "")[:60]
    logger.info(f"Processing article_id={article_id} title={title!r}")

    try:
        parsed = _ask_claude(body)
    except ClaudeResponseError as e:
        logger.warning(f"Claude permanent failure for {article_id}: {e}")
        _safe_failure_callback(article_id, str(e))
        return
    except anthropic.APIStatusError as e:
        if 400 <= e.status_code < 500:
            logger.warning(f"Claude {e.status_code} (permanent) for {article_id}: {e}")
            _safe_failure_callback(article_id, f"claude {e.status_code}")
            return
        raise  # 5xx → transient → let SQS retry

    payload = {
        "article_id": article_id,
        "ai_problem": parsed.get("problem", ""),
        "ai_solution": parsed.get("solution", ""),
        "ai_concepts": parsed.get("concepts", []),
        "tags": parsed.get("tags", []),
    }
    status = _post_callback(payload)
    if 200 <= status < 300:
        logger.info(f"Callback POST → {status} for article_id={article_id}")
    else:
        # 4xx — already POSTed once; retrying won't change Flask's mind.
        # Log loudly so the user notices in CloudWatch (sig mismatch, deleted
        # article, etc.) but don't trigger SQS retry → DLQ.
        logger.warning(
            f"Callback POST → {status} (permanent) for article_id={article_id} — acking"
        )


def lambda_handler(event: dict, context) -> dict:
    """
    SQS-invoked entry point.

    Returns partial batch failure response so successful messages get deleted
    from the queue even when peers fail. Enable on the event source mapping:
        ReportBatchItemFailures: true

    On config errors (missing env vars), raises out of the handler — this
    fails the invocation visibly. SQS keeps every message in the batch and
    retries; CloudWatch fires on Lambda Errors > 0.
    """
    _validate_env()

    failures = []
    for record in event.get("Records", []):
        try:
            _process_record(record)
        except Exception as e:
            logger.exception(
                f"Transient failure on messageId={record.get('messageId')}: {e}"
            )
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
