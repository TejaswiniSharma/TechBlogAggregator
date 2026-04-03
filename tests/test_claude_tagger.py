"""
Tests for ai_tagger/claude_tagger.py — Claude API integration.
Priority 5: Mocks the Anthropic client. Never makes real API calls.
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock
from ai_tagger.claude_tagger import analyze_article, _get_client


class TestAnalyzeArticle:
    @pytest.fixture
    def sample_article(self):
        return {
            "title": "Scaling Cache at Netflix",
            "summary": "How Netflix handles cache invalidation at massive scale.",
            "company": "Netflix",
            "tags_hint": ["distributed-systems", "caching"],
            "tags": ["general"],
        }

    def _mock_response(self, text):
        """Create a mock Claude API response."""
        mock_content = MagicMock()
        mock_content.text = text
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        return mock_response

    @patch("ai_tagger.claude_tagger._get_client")
    def test_parses_valid_response(self, mock_client_fn, sample_article):
        response_json = json.dumps({
            "problem": "Cache invalidation at scale",
            "solution": "Used consistent hashing with TTL-based expiry",
            "concepts": ["consistent hashing", "TTL", "cache invalidation"],
            "study_summary": "Netflix solved cache invalidation using consistent hashing.",
            "tags": ["caching", "distributed-systems"],
        })
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_response(response_json)
        mock_client_fn.return_value = mock_client

        result = analyze_article(sample_article)
        assert result["ai_summary"]["problem"] == "Cache invalidation at scale"
        assert result["ai_summary"]["solution"] == "Used consistent hashing with TTL-based expiry"
        assert "consistent hashing" in result["ai_summary"]["concepts"]
        assert result["tags"] == ["caching", "distributed-systems"]

    @patch("ai_tagger.claude_tagger._get_client")
    def test_handles_json_parse_failure(self, mock_client_fn, sample_article):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_response("This is not JSON at all")
        mock_client_fn.return_value = mock_client

        result = analyze_article(sample_article)
        assert result["ai_summary"]["problem"] == "Could not parse AI response."
        assert isinstance(result["tags"], list)

    @patch("ai_tagger.claude_tagger._get_client")
    def test_empty_summary_uses_fallback(self, mock_client_fn):
        article = {
            "title": "LinkedIn Search Stack",
            "summary": "",
            "company": "LinkedIn",
            "tags_hint": ["search"],
            "tags": ["general"],
        }
        response_json = json.dumps({
            "problem": "Search scaling",
            "solution": "Rebuilt search infra",
            "concepts": ["inverted index"],
            "study_summary": "LinkedIn rebuilt search.",
            "tags": ["search"],
        })
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_response(response_json)
        mock_client_fn.return_value = mock_client

        result = analyze_article(article)
        # Should still produce valid output even with empty summary
        assert result["ai_summary"]["problem"] == "Search scaling"

        # Verify the prompt contained the fallback text
        call_args = mock_client.messages.create.call_args
        prompt_text = call_args[1]["messages"][0]["content"]
        assert "No article summary available" in prompt_text

    @patch("ai_tagger.claude_tagger._get_client")
    def test_handles_missing_fields_in_response(self, mock_client_fn, sample_article):
        # Claude returns JSON missing some keys
        response_json = json.dumps({
            "problem": "A problem",
            "solution": "A solution",
            # Missing: concepts, study_summary, tags
        })
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_response(response_json)
        mock_client_fn.return_value = mock_client

        result = analyze_article(sample_article)
        assert result["ai_summary"]["problem"] == "A problem"
        assert result["ai_summary"]["concepts"] == []  # default
        assert isinstance(result["tags"], list)  # falls back to original

    def test_missing_api_key_raises(self):
        # Reset the cached client
        import ai_tagger.claude_tagger as tagger
        original_client = tagger._client
        tagger._client = None

        with patch.dict(os.environ, {}, clear=True):
            # Remove ANTHROPIC_API_KEY if set
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(EnvironmentError, match="ANTHROPIC_API_KEY"):
                _get_client()

        # Restore
        tagger._client = original_client

    @patch("ai_tagger.claude_tagger._get_client")
    def test_prompt_contains_article_fields(self, mock_client_fn, sample_article):
        response_json = json.dumps({
            "problem": "x", "solution": "y", "concepts": [],
            "study_summary": "z", "tags": ["general"],
        })
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_response(response_json)
        mock_client_fn.return_value = mock_client

        analyze_article(sample_article)

        call_args = mock_client.messages.create.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "Netflix" in prompt
        assert "Scaling Cache at Netflix" in prompt
        assert "cache invalidation" in prompt
