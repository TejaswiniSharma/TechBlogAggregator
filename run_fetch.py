#!/usr/bin/env python3
# run_fetch.py
#
# This is the entry point — the script you actually RUN.
# It wires together config -> fetcher -> storage and gives you a CLI interface.
#
# USAGE:
#   python run_fetch.py                          # fetch all blogs
#   python run_fetch.py --company Netflix        # fetch only Netflix
#   python run_fetch.py --list-topics            # show available interview topics
#   python run_fetch.py --filter-topic caching   # show cached articles on 'caching'
#   python run_fetch.py --filter-topic microservices --company Uber
#
# WHY argparse and not a config file or env vars?
# CLI flags are the simplest 'UI' for a script you'll run interactively.
# argparse handles --help, type validation, and defaults for free.

import argparse
import sys
from config.blogs import BLOGS
from fetcher.rss_fetcher import fetch_all_blogs, fetch_blog
from fetcher.storage import add_articles, get_articles
from fetcher.topic_tagger import get_all_topics


def cmd_fetch(args):
    """Fetch new articles from configured blogs."""
    blogs_to_fetch = BLOGS

    # If --company flag provided, filter to just that company's blog
    if args.company:
        blogs_to_fetch = [b for b in BLOGS if b["company"].lower() == args.company.lower()]
        if not blogs_to_fetch:
            print(f"[ERROR] No blog configured for company: {args.company}")
            print(f"Available companies: {', '.join(b['company'] for b in BLOGS)}")
            sys.exit(1)

    print(f"\n=== Fetching {len(blogs_to_fetch)} blog(s) ===\n")
    articles = fetch_all_blogs(blogs_to_fetch)

    print(f"\n=== Storing articles ===")
    result = add_articles(articles)
    print(f"  Added:   {result['added']} new articles")
    print(f"  Skipped: {result['skipped']} already seen")
    print(f"  Total:   {result['total']} articles in store")


def cmd_list(args):
    """
    List articles from the store, with optional filters.
    This is 'interview prep mode' — pick a topic, see what big tech wrote about it.
    """
    articles = get_articles(
        topic=args.topic or "all",
        company=args.company or "all",
        limit=args.limit
    )

    if not articles:
        print(f"\nNo articles found. Try: python run_fetch.py (to fetch first)\n")
        return

    # Display header
    filter_desc = []
    if args.topic: filter_desc.append(f"topic={args.topic}")
    if args.company: filter_desc.append(f"company={args.company}")
    filters = f" [{', '.join(filter_desc)}]" if filter_desc else ""

    print(f"\n=== Articles{filters} — {len(articles)} results ===\n")

    for i, article in enumerate(articles, 1):
        tags_display = ", ".join(article.get("tags", [])[:4])  # show max 4 tags
        print(f"  {i:3}. [{article['company']:10}] {article['title'][:65]}")
        print(f"       Tags: {tags_display}")
        print(f"       URL:  {article['url']}")
        print()


def cmd_topics(args):
    """Show all available interview topics for filtering."""
    topics = get_all_topics()
    print(f"\n=== {len(topics)} Interview Topics Available ===\n")
    for topic in topics:
        print(f"  --filter-topic {topic}")
    print(f"\nExample: python run_fetch.py --filter-topic caching\n")


def main():
    parser = argparse.ArgumentParser(
        description="Tech Blog Learning System — Subsystem 1: Blog Fetcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_fetch.py                                   Fetch all blogs
  python run_fetch.py --company Netflix                 Fetch only Netflix
  python run_fetch.py --list-topics                     Show all interview topics
  python run_fetch.py --filter-topic caching            Show articles on caching
  python run_fetch.py --filter-topic microservices --limit 10
        """
    )

    # Mutually exclusive modes
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--list-topics",
        action="store_true",
        help="Show all available interview topic filters"
    )
    mode_group.add_argument(
        "--filter-topic",
        metavar="TOPIC",
        dest="topic",
        help="Show stored articles filtered by interview topic"
    )

    # Shared optional flags
    parser.add_argument(
        "--company",
        metavar="NAME",
        help="Filter by company (Netflix, Uber, Spotify, etc.)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        metavar="N",
        help="Max articles to show (default: 20)"
    )

    args = parser.parse_args()

    # Route to the right command
    # WHY not if/elif chains? With more commands this grows ugly.
    # In a real CLI tool (click, typer), subcommands handle this cleanly.
    # We're keeping it simple for learning.
    if args.list_topics:
        cmd_topics(args)
    elif args.topic:
        cmd_list(args)
    elif args.company:
        # Company flag without --filter-topic = fetch mode for that company
        cmd_fetch(args)
    else:
        # No flags = fetch everything
        cmd_fetch(args)


if __name__ == "__main__":
    main()
