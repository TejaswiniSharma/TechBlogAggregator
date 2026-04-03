#!/usr/bin/env python3
# run_ai_tag.py
#
# Subsystem 2 entry point — AI Tagger.
# Reads articles from articles.json, sends each to Claude, writes analysis back.
#
# USAGE:
#   export ANTHROPIC_API_KEY="sk-ant-..."
#
#   python3 run_ai_tag.py               # process all unanalyzed articles
#   python3 run_ai_tag.py --limit 5     # process only 5 (good for testing cost)
#   python3 run_ai_tag.py --company Netflix   # process only Netflix articles
#   python3 run_ai_tag.py --reprocess   # re-run even already-analyzed articles
#
# WHY a separate entry point (not merged into run_fetch.py)?
# Fetch (Subsystem 1) runs frequently and costs nothing.
# AI tagging (Subsystem 2) costs API credits and is slower.
# Keeping them separate lets you run them on different schedules.

import argparse
import sys
from fetcher.storage import get_articles, update_article_ai_analysis
from ai_tagger.claude_tagger import analyze_article


def main():
    parser = argparse.ArgumentParser(
        description="Tech Blog Learning System — Subsystem 2: AI Tagger",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run_ai_tag.py                   Process all new articles
  python3 run_ai_tag.py --limit 5         Process 5 articles (cost-safe testing)
  python3 run_ai_tag.py --company Netflix Process only Netflix articles
  python3 run_ai_tag.py --reprocess       Re-analyze already-processed articles
        """
    )

    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Max number of articles to process (omit for all)"
    )
    parser.add_argument(
        "--company",
        metavar="NAME",
        help="Only process articles from this company"
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Re-analyze articles that already have AI analysis"
    )

    args = parser.parse_args()

    # Load articles with optional company filter
    articles = get_articles(company=args.company or "all")

    if not articles:
        print("\nNo articles found. Run: python3 run_fetch.py first.\n")
        sys.exit(0)

    # By default, skip articles that already have valid AI analysis
    # WHY? Each API call costs money. Don't reprocess unless asked.
    if not args.reprocess:
        before = len(articles)
        articles = [a for a in articles if "ai_summary" not in a]
        skipped_already_done = before - len(articles)
        if skipped_already_done:
            print(f"  Skipping {skipped_already_done} already-analyzed articles (use --reprocess to redo)")
    else:
        print(f"  Reprocessing all {len(articles)} articles (--reprocess flag set)")

    if not articles:
        print("\nAll articles already analyzed. Use --reprocess to re-run.\n")
        sys.exit(0)

    # Apply limit AFTER filtering — so --limit 5 means "5 new ones", not "5 total"
    if args.limit:
        articles = articles[:args.limit]

    total = len(articles)
    print(f"\n=== AI Tagging {total} article(s) ===\n")

    succeeded = 0
    failed = 0

    for i, article in enumerate(articles, 1):
        title_preview = article.get("title", "")[:55]
        company = article.get("company", "?")
        print(f"  [{i}/{total}] [{company}] {title_preview}...")

        try:
            analysis = analyze_article(article)
            update_article_ai_analysis(article["url"], analysis)

            # Show a preview of what Claude extracted
            ai = analysis["ai_summary"]
            print(f"    Problem:   {ai['problem'][:80]}")
            print(f"    Concepts:  {', '.join(ai['concepts'][:4])}")
            print(f"    Tags:      {', '.join(analysis['tags'])}")
            print()
            succeeded += 1

        except Exception as e:
            print(f"    [ERROR] {e}\n")
            failed += 1

    # Summary
    print(f"=== Done ===")
    print(f"  Analyzed: {succeeded}")
    if failed:
        print(f"  Failed:   {failed}")
    print(f"\nNext: python3 run_fetch.py --filter-topic caching  (tags are now AI-refined)")


if __name__ == "__main__":
    main()
