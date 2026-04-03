# fetcher/ai_tagger.py
#
# WHY THIS FILE EXISTS:
# Subsystem 2: AI-powered article analysis using the Claude API.
# The keyword tagger in topic_tagger.py can only detect topics when the article
# EXPLICITLY says "redis" or "kafka". Claude understands CONCEPTS — it reads
# "we store hot data closer to users" and knows that's caching even without the word.
#
# HOW THIS RELATES TO topic_tagger.py:
# topic_tagger.py:  keyword matching — free, instant, offline, misses ~52% of articles
# ai_tagger.py:     Claude API — costs ~$0.006/article, takes ~2s, understands meaning
# Both produce 'tags' in the same format — ai_tagger UPDATES the tags field in place.
# After AI tagging, --filter-topic still works exactly as before (no schema changes needed).
#
# ARCHITECTURE DECISION — WHY DECOUPLE TAGGING FROM FETCHING?
# Running a Claude API call for every article during fetch_blog() would make the fetcher
# ~100x slower and couple network I/O with LLM cost. Instead, tagging is a separate pass:
#   1. Fetch articles fast (RSS, no AI)
#   2. Tag articles separately (AI, on demand)
# This mirrors Airbnb's "Minerva" architecture: separate data ingestion from computation.
# It also means you can re-tag existing articles without re-fetching RSS feeds.
#
# COST AWARENESS:
# Claude Opus 4.6: $5.00/1M input tokens, $25.00/1M output tokens
# Per article: ~400 input tokens + ~175 output tokens ≈ $0.006
# 79 articles: ~$0.50 — reasonable for a one-time setup run
# Use --dry-run to preview before committing API spend.

import json
import time
from typing import Optional

import anthropic

from fetcher.topic_tagger import TOPIC_KEYWORDS

# Single source of truth for valid topics — imported from topic_tagger.py.
# WHY not hardcode them here? If someone adds a new topic to TOPIC_KEYWORDS,
# it should automatically become available to the AI tagger too.
VALID_TOPICS = sorted(TOPIC_KEYWORDS.keys())

# JSON schema for Claude's structured output.
#
# WHY use output_config.format instead of asking Claude to "return JSON in your answer"?
# Without structured output, Claude might wrap its response in markdown code fences
# (```json ... ```) or add a preamble like "Here is the analysis:". That breaks
# json.loads() and requires fragile post-processing.
# output_config.format GUARANTEES the response text is valid JSON matching this schema.
# Same reason you use prepared statements for SQL — enforce the format, don't hope for it.
#
# WHY include an enum for tags?
# It constrains Claude to our exact topic taxonomy. Without it, Claude might invent
# tags like "distributed-computing" instead of "distributed-systems" — close, but
# incompatible with --filter-topic. The enum makes mismatches structurally impossible.
_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "problem": {
            "type": "string",
            "description": (
                "The core engineering problem this article addresses. "
                "What broke, what didn't scale, what was too slow? (1-2 sentences)"
            ),
        },
        "solution": {
            "type": "string",
            "description": (
                "The main technical approach or architectural decision described. "
                "What changed to fix or improve the system? (1-2 sentences)"
            ),
        },
        "concepts": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "3-5 specific system design concepts covered. Be precise: "
                "'write-ahead logging' not 'storage', 'consistent hashing' not 'distributed'."
            ),
        },
        "tags": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": VALID_TOPICS,
            },
            "description": (
                "1-3 interview topic categories from the provided list that best match "
                "the article. Pick the most relevant — don't force-fit all of them."
            ),
        },
    },
    "required": ["problem", "solution", "concepts", "tags"],
    "additionalProperties": False,
}

# System prompt is extracted as a constant for two reasons:
# 1. It's long — keeping it out of the function body keeps the function readable.
# 2. Prompt caching: if you add cache_control later, a constant system prompt
#    is a natural cache boundary (same text = same cache key).
_SYSTEM_PROMPT = f"""You are analyzing engineering blog posts for a system design interview study tool.

Given an article title and summary from a major tech company blog, extract:

- problem:  The core engineering challenge (what was broken, slow, or didn't scale)
- solution: The architectural approach taken to address the problem
- concepts: 3-5 specific, named system design concepts (e.g. "bloom filter", "write-ahead log",
            "consistent hashing", "saga pattern" — not vague terms like "scalability")
- tags:     1-3 topic categories from this exact list: {', '.join(VALID_TOPICS)}

Focus on what a software engineer preparing for system design interviews would want to know.
If the summary is thin, use the company context and title to infer the likely content."""


def analyze_article(article: dict, client: anthropic.Anthropic) -> Optional[dict]:
    """
    Analyze one article with Claude and return structured AI analysis.

    Args:
        article: One article dict from articles.json (needs 'title', 'summary', 'company')
        client:  Initialized Anthropic client — passed in rather than created here

    Returns:
        {"ai_summary": {problem, solution, concepts}, "tags": [topic, ...]}
        or None if the API call fails.

    WHY pass the client in instead of creating it inside this function?
    Creating anthropic.Anthropic() reads the API key and sets up HTTP configuration.
    It's cheap, but creating it 79 times is wasteful. Passing it in lets the caller
    create it once and reuse it — the same reason database connection pools exist.

    WHY return None on failure instead of raising an exception?
    One bad article (rate limit burst, malformed response, network blip) should NOT
    abort a 79-article tagging run that's already 60% done. The caller (run_tag.py)
    tracks failures and continues. This is the bulkhead pattern — same as rss_fetcher.py.

    WHY use thinking: adaptive?
    Most articles are simple extractions that need no deep reasoning. Adaptive thinking
    lets Claude decide whether to think. For a 500-char summary, it usually won't,
    keeping latency and cost low. For ambiguous articles, it can reason before tagging.
    """
    user_message = (
        f"Article title: {article['title']}\n\n"
        f"Article summary: {article.get('summary', 'No summary available.')}\n\n"
        f"Company: {article.get('company', 'Unknown')}"
    )

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=_SYSTEM_PROMPT,
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": _ANALYSIS_SCHEMA,
                }
            },
            messages=[{"role": "user", "content": user_message}],
        )

        # Extract text block — thinking blocks (if any) come first in content list
        text = next((b.text for b in response.content if b.type == "text"), None)
        if not text:
            return None

        data = json.loads(text)

        # Defense-in-depth: filter tags to known valid topics even though the schema
        # already constrains them. The API guarantees schema compliance, but this
        # makes the code correct regardless of any future schema changes.
        valid_tags = [t for t in data.get("tags", []) if t in VALID_TOPICS]
        tags = valid_tags if valid_tags else ["general"]

        return {
            "ai_summary": {
                "problem": data["problem"],
                "solution": data["solution"],
                "concepts": data["concepts"],
            },
            "tags": tags,
        }

    except anthropic.AuthenticationError:
        # Wrong or missing API key — no point continuing the run.
        # Re-raise so run_tag.py can give the user a clear error message.
        raise

    except Exception as e:
        # Any other failure (network, rate limit after SDK retries, bad response) —
        # log it and return None so the caller can skip this article and continue.
        print(f"    [ERROR] {type(e).__name__}: {e}")
        return None
