"""
Tests for fetcher/topic_tagger.py — keyword-based topic tagger.
Priority 2: Pure logic, no I/O. Catches silent misclassification.
"""

import pytest
from fetcher.topic_tagger import tag_article, get_all_topics


class TestTagArticle:
    def test_matches_single_topic(self):
        tags = tag_article("Redis cache invalidation strategies", "")
        assert "caching" in tags

    def test_matches_multiple_topics(self):
        tags = tag_article("Kafka on Kubernetes", "Message queues in a microservice mesh")
        assert "messaging-queues" in tags
        assert "microservices" in tags

    def test_case_insensitive(self):
        tags_lower = tag_article("redis caching", "")
        tags_upper = tag_article("REDIS CACHING", "")
        tags_mixed = tag_article("Redis Caching", "")
        assert "caching" in tags_lower
        assert "caching" in tags_upper
        assert "caching" in tags_mixed

    def test_no_match_returns_general(self):
        tags = tag_article("Company Q4 Earnings Report", "Financial results summary")
        assert tags == ["general"]

    def test_empty_inputs(self):
        tags = tag_article("", "")
        assert tags == ["general"]

    def test_keyword_in_summary_not_title(self):
        tags = tag_article("A blog post", "We used consistent hashing and redis for our cache layer")
        assert "caching" in tags

    def test_returns_list(self):
        tags = tag_article("Distributed systems at scale", "")
        assert isinstance(tags, list)
        assert len(tags) > 0


class TestGetAllTopics:
    def test_returns_sorted(self):
        topics = get_all_topics()
        assert topics == sorted(topics)

    def test_contains_known_topics(self):
        topics = get_all_topics()
        expected = ["caching", "databases", "distributed-systems", "microservices", "search"]
        for topic in expected:
            assert topic in topics

    def test_returns_all_15_topics(self):
        topics = get_all_topics()
        assert len(topics) == 15
