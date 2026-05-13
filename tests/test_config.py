"""
Tests for config/blogs.py — blog configuration list and its module-level validation.

The validation block at the bottom of blogs.py runs three assertions over every
entry in BLOGS at import time:

    assert "name" in _blog and "company" in _blog
    assert "rss_url" in _blog or "scrape_url" in _blog
    assert "tags_hint" in _blog

Because the assertions execute during import (not inside a function), we cannot
re-trigger them by calling a function.  Instead, we extract an equivalent
validate_blog helper here and use it for negative-case tests.  This keeps the
tests readable and avoids importlib tricks while still covering every branch of
the original logic.
"""

import pytest
from config.blogs import BLOGS


# ---------------------------------------------------------------------------
# Helper — mirrors the module-level validation loop exactly
# ---------------------------------------------------------------------------

def _validate_blogs(blogs):
    """Run the same assertions as the module-level loop in blogs.py."""
    for blog in blogs:
        assert "name" in blog and "company" in blog, f"Missing required keys in: {blog}"
        assert "rss_url" in blog or "scrape_url" in blog, f"No fetch URL in: {blog['name']}"
        assert "tags_hint" in blog, f"Missing tags_hint in: {blog['name']}"


# ---------------------------------------------------------------------------
# Minimal valid blog fixtures used across multiple test classes
# ---------------------------------------------------------------------------

def _rss_blog(**overrides):
    """Return a minimal valid blog dict that uses rss_url."""
    base = {
        "name": "Example RSS Blog",
        "company": "ExampleCo",
        "rss_url": "https://example.com/feed.rss",
        "tags_hint": ["scalability", "databases"],
    }
    base.update(overrides)
    return base


def _scrape_blog(**overrides):
    """Return a minimal valid blog dict that uses scrape_url (no rss_url)."""
    base = {
        "name": "Example Scrape Blog",
        "company": "ScrapeCo",
        "scrape_url": "https://example.com/engineering/",
        "tags_hint": ["distributed-systems"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TestRealBlogsPassValidation
# Happy-path: the production BLOGS list must pass all three assertions.
# ---------------------------------------------------------------------------

class TestRealBlogsPassValidation:
    def test_blogs_list_is_non_empty(self):
        assert len(BLOGS) > 0

    def test_all_blogs_pass_validation(self):
        # Should not raise — covers the happy path end-to-end.
        _validate_blogs(BLOGS)

    def test_every_blog_has_name(self):
        for blog in BLOGS:
            assert "name" in blog, f"Blog missing 'name': {blog}"

    def test_every_blog_has_company(self):
        for blog in BLOGS:
            assert "company" in blog, f"Blog missing 'company': {blog}"

    def test_every_blog_has_at_least_one_fetch_url(self):
        for blog in BLOGS:
            has_url = "rss_url" in blog or "scrape_url" in blog
            assert has_url, f"Blog '{blog['name']}' has neither rss_url nor scrape_url"

    def test_every_blog_has_tags_hint(self):
        for blog in BLOGS:
            assert "tags_hint" in blog, f"Blog '{blog['name']}' missing tags_hint"

    def test_tags_hint_is_a_list(self):
        for blog in BLOGS:
            assert isinstance(blog["tags_hint"], list), (
                f"Blog '{blog['name']}' tags_hint should be a list, got {type(blog['tags_hint'])}"
            )

    def test_tags_hint_is_non_empty(self):
        for blog in BLOGS:
            assert len(blog["tags_hint"]) > 0, (
                f"Blog '{blog['name']}' has an empty tags_hint list"
            )

    def test_scrape_only_blogs_present(self):
        # LinkedIn, Uber, DoorDash, and Shopify are known scrape-only entries.
        # Confirm at least one scrape-only blog exists so we know that path is exercised.
        scrape_only = [
            b for b in BLOGS if "scrape_url" in b and "rss_url" not in b
        ]
        assert len(scrape_only) > 0, "Expected at least one scrape-only blog in BLOGS"


# ---------------------------------------------------------------------------
# TestMissingNameOrCompany
# Validation rule 1: both 'name' and 'company' must be present.
# ---------------------------------------------------------------------------

class TestMissingNameOrCompany:
    def test_missing_name_raises(self):
        bad = _rss_blog()
        del bad["name"]
        with pytest.raises(AssertionError, match="Missing required keys"):
            _validate_blogs([bad])

    def test_missing_company_raises(self):
        bad = _rss_blog()
        del bad["company"]
        with pytest.raises(AssertionError, match="Missing required keys"):
            _validate_blogs([bad])

    def test_missing_both_name_and_company_raises(self):
        bad = _rss_blog()
        del bad["name"]
        del bad["company"]
        with pytest.raises(AssertionError, match="Missing required keys"):
            _validate_blogs([bad])

    def test_valid_blog_with_name_and_company_passes(self):
        _validate_blogs([_rss_blog()])  # must not raise

    def test_error_is_raised_for_offending_blog_not_earlier_one(self):
        # First blog is valid; second is missing 'company'.
        # The loop must reach and flag the second entry.
        good = _rss_blog(name="Good Blog", company="GoodCo")
        bad = _rss_blog(name="Bad Blog")
        del bad["company"]
        with pytest.raises(AssertionError, match="Missing required keys"):
            _validate_blogs([good, bad])


# ---------------------------------------------------------------------------
# TestMissingFetchUrl
# Validation rule 2: at least one of 'rss_url' or 'scrape_url' must be present.
# ---------------------------------------------------------------------------

class TestMissingFetchUrl:
    def test_missing_both_urls_raises(self):
        bad = _rss_blog()
        del bad["rss_url"]  # now has neither rss_url nor scrape_url
        with pytest.raises(AssertionError, match="No fetch URL"):
            _validate_blogs([bad])

    def test_error_message_includes_blog_name(self):
        bad = _rss_blog(name="My Special Blog")
        del bad["rss_url"]
        with pytest.raises(AssertionError, match="My Special Blog"):
            _validate_blogs([bad])

    def test_rss_url_alone_passes(self):
        _validate_blogs([_rss_blog()])  # has rss_url, no scrape_url

    def test_scrape_url_alone_passes(self):
        _validate_blogs([_scrape_blog()])  # has scrape_url, no rss_url

    def test_both_urls_present_passes(self):
        both = _rss_blog(scrape_url="https://example.com/engineering/")
        _validate_blogs([both])  # having both is also fine

    def test_valid_blog_followed_by_url_less_blog_raises(self):
        good = _scrape_blog()
        bad = _rss_blog()
        del bad["rss_url"]
        with pytest.raises(AssertionError, match="No fetch URL"):
            _validate_blogs([good, bad])


# ---------------------------------------------------------------------------
# TestMissingTagsHint
# Validation rule 3: 'tags_hint' must be present.
# ---------------------------------------------------------------------------

class TestMissingTagsHint:
    def test_missing_tags_hint_raises(self):
        bad = _rss_blog()
        del bad["tags_hint"]
        with pytest.raises(AssertionError, match="Missing tags_hint"):
            _validate_blogs([bad])

    def test_error_message_includes_blog_name(self):
        bad = _rss_blog(name="Hint-Less Blog")
        del bad["tags_hint"]
        with pytest.raises(AssertionError, match="Hint-Less Blog"):
            _validate_blogs([bad])

    def test_tags_hint_present_passes(self):
        _validate_blogs([_rss_blog()])  # must not raise

    def test_scrape_blog_without_tags_hint_raises(self):
        bad = _scrape_blog()
        del bad["tags_hint"]
        with pytest.raises(AssertionError, match="Missing tags_hint"):
            _validate_blogs([bad])


# ---------------------------------------------------------------------------
# TestScrapeUrlStrategy
# Blogs with only 'scrape_url' (no 'rss_url') must pass all three rules.
# This validates that the OR in rule 2 works for the scraper path.
# ---------------------------------------------------------------------------

class TestScrapeUrlStrategy:
    def test_scrape_only_blog_passes_all_rules(self):
        blog = _scrape_blog()
        assert "rss_url" not in blog  # confirm the fixture really is scrape-only
        _validate_blogs([blog])       # must not raise

    def test_scrape_only_blog_with_all_required_fields_passes(self):
        blog = {
            "name": "LinkedIn Engineering",
            "company": "LinkedIn",
            "scrape_url": "https://www.linkedin.com/blog/engineering/",
            "tags_hint": ["distributed-systems", "ml-at-scale"],
        }
        _validate_blogs([blog])

    def test_list_mixing_rss_and_scrape_blogs_passes(self):
        blogs = [_rss_blog(), _scrape_blog()]
        _validate_blogs(blogs)  # must not raise


# ---------------------------------------------------------------------------
# TestEmptyAndEdgeCases
# ---------------------------------------------------------------------------

class TestEmptyAndEdgeCases:
    def test_empty_blogs_list_passes(self):
        # An empty list should not raise — there is nothing to violate.
        _validate_blogs([])

    def test_single_valid_rss_blog_passes(self):
        _validate_blogs([_rss_blog()])

    def test_single_valid_scrape_blog_passes(self):
        _validate_blogs([_scrape_blog()])

    def test_name_empty_string_passes_key_check_but_is_present(self):
        # The assertion only checks key presence, not that the value is non-empty.
        # An empty string for 'name' satisfies `"name" in blog`.
        blog = _rss_blog(name="")
        _validate_blogs([blog])  # must not raise — rule 1 checks key presence only

    def test_tags_hint_empty_list_passes_key_check(self):
        # Similarly, an empty list satisfies `"tags_hint" in blog`.
        blog = _rss_blog(tags_hint=[])
        _validate_blogs([blog])  # must not raise — rule 3 checks key presence only

    def test_extra_keys_do_not_break_validation(self):
        blog = _rss_blog(extra_field="ignored", another_field=42)
        _validate_blogs([blog])  # extra keys must not cause failures
