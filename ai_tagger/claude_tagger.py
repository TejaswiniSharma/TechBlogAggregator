# ai_tagger/claude_tagger.py
#
# WHY THIS FILE EXISTS:
# Subsystem 1 tags articles with keywords — fast and free, but limited.
# This is Subsystem 2: we send each article to Claude and get back a structured
# analysis that keyword matching could never produce.
#
# WHAT CLAUDE EXTRACTS:
#   core_problem      — What engineering challenge was the company actually solving?
#   solution          — How did they solve it? (the interesting part)
#   interview_concepts — Which system design concepts does this teach?
#   study_summary     — One-paragraph plain-English summary for quick review
#   tags              — Refined topic tags (replaces/extends keyword tags)
#
# WHY JSON OUTPUT FROM CLAUDE?
# We need machine-readable output to write back into articles.json.
# Asking Claude to respond in JSON with a defined schema is the standard pattern
# for structured extraction. The alternative (parsing free-text) is fragile.
#
# WHY NOT STREAM THE RESPONSE?
# Streaming is useful for UIs where the user watches tokens appear.
# Here we need the full JSON before we can parse it. Streaming adds complexity
# with no benefit. Start simple — add streaming later if you need it for a UI.

import json
import os
import anthropic

# WHY load the key from an env var?
# Never hardcode API keys. If you commit a key to git, you must rotate it immediately.
# Environment variables are the 12-Factor App standard for secrets.
# Set it with: export ANTHROPIC_API_KEY="sk-ant-..."
_client = None


def _get_client() -> anthropic.Anthropic:
    """
    Lazily initialize the Anthropic client.

    WHY lazy initialization (not module-level)?
    If we create the client at import time and ANTHROPIC_API_KEY isn't set,
    the import itself crashes — even for commands that don't need the AI tagger.
    Lazy init means: only fail when the user actually tries to use AI tagging.
    """
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "\n[ERROR] ANTHROPIC_API_KEY environment variable not set.\n"
                "Get your key from: https://console.anthropic.com/\n"
                "Then run: export ANTHROPIC_API_KEY='sk-ant-...'\n"
            )
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


# The prompt template.
# WHY a module-level constant instead of inline string?
# Easy to read, review, and update without digging into function logic.
# The prompt IS the core logic of this subsystem — it deserves visibility.
_ANALYSIS_PROMPT = """\
You are analyzing a tech engineering blog post for a software engineer studying system design for interviews.

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
  "study_summary": "Three to four sentences combining the problem, solution, and what a system design candidate should take away from this.",
  "tags": ["list", "of", "relevant topic tags", "from this set only: caching, rate-limiting, distributed-systems, databases, messaging-queues, microservices, load-balancing, observability, ml-systems, search, real-time-systems, storage-systems, api-design, security, chaos-engineering, general"]
}}

Rules:
- Be specific to THIS article, not generic advice.
- concepts should be concrete terms (e.g. "write-ahead log", "consistent hashing") not vague labels.
- tags must only use values from the allowed set above.
- If the summary is too short to extract meaningful insight, still do your best with what's available.
"""


def analyze_article(article: dict) -> dict:
    """
    Send one article to Claude and get back a structured analysis.

    Args:
        article: One article dict from articles.json (needs: title, summary, company, tags_hint)

    Returns:
        {
            "ai_summary": {
                "core_problem": str,
                "solution": str,
                "interview_concepts": list[str],
                "study_summary": str
            },
            "tags": list[str]
        }

    WHY separate ai_summary from tags in the return value?
    storage.update_article_ai_analysis() merges these back differently:
    - ai_summary is stored as a nested object (new field, additive)
    - tags REPLACES the keyword tags (upgrade in place, transparent to callers)
    Keeping them separate in the return value makes the caller's intent clear.

    INTERVIEW INSIGHT:
    This function is a classic 'adapter' pattern. It translates between two
    representations: the article dict (our schema) and the Claude API (external schema).
    Stripe uses this for payment provider adapters; the rest of the system never
    knows which provider is underneath.
    """
    client = _get_client()

    summary = article.get("summary", "") or ""
    if not summary.strip():
        # LinkedIn and other scraped articles may lack summaries.
        # Use the title as the only context — Claude can still infer topics.
        summary = f"(No article summary available. Analyze based on the title alone.)"

    prompt = _ANALYSIS_PROMPT.format(
        company=article.get("company", "Unknown"),
        tags_hint=", ".join(article.get("tags_hint", [])) or "general engineering",
        title=article.get("title", ""),
        summary=summary,
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",  # Fast + cheap — right tool for batch processing
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract the text content from the response
    raw_text = response.content[0].text.strip()

    # Parse the JSON Claude returned
    # WHY wrap in try/except? Claude very reliably returns valid JSON when asked,
    # but network issues or truncated responses can cause malformed output.
    # We never want one bad API response to crash a 79-article batch run.
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        # Fallback: return a minimal valid structure so the run continues
        print(f"    [WARN] JSON parse failed for: {article.get('title', '')[:50]}")
        parsed = {
            "problem": "Could not parse AI response.",
            "solution": "Could not parse AI response.",
            "concepts": [],
            "study_summary": article.get("summary", ""),
            "tags": article.get("tags", ["general"]),
        }

    return {
        "ai_summary": {
            "problem": parsed.get("problem", ""),
            "solution": parsed.get("solution", ""),
            "concepts": parsed.get("concepts", []),
            "study_summary": parsed.get("study_summary", ""),
        },
        "tags": parsed.get("tags", article.get("tags", ["general"])),
    }
