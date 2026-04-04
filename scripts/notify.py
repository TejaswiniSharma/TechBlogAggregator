#!/usr/bin/env python3
"""
Send an email summary of newly fetched articles via AWS SES.
Called by weekly_update.sh after the fetch + tag steps.

Usage: python3 scripts/notify.py <num_new_articles>
"""

import json
import os
import sqlite3
import sys
import boto3
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(PROJECT_ROOT, "data", "techblogs.db")

SENDER = "teju.aswini21@gmail.com"
RECIPIENT = "teju.aswini21@gmail.com"
AWS_REGION = "us-east-2"


def get_this_weeks_articles():
    """Get articles fetched in the last 7 days."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        "SELECT title, company, url FROM articles WHERE fetched_at > ? ORDER BY company, title",
        (cutoff,)
    ).fetchall()
    conn.close()
    return rows


def send_email(new_count):
    articles = get_this_weeks_articles()

    if not articles:
        print("No new articles to notify about.")
        return

    # Build article list for email
    article_lines = []
    for a in articles:
        article_lines.append(f"  • [{a['company']}] {a['title']}\n    {a['url']}")

    body_text = f"""Hi Tejaswini,

{new_count} new article(s) were fetched this week for Distributed Readings.

This week's articles:
{chr(10).join(article_lines)}

Visit your site: http://18.222.252.226

— Distributed Readings Bot
"""

    body_html = f"""<html>
<body style="font-family: Inter, sans-serif; color: #2C2416; background: #FAF7F1; padding: 24px;">
  <div style="max-width: 600px; margin: 0 auto;">
    <h2 style="font-family: Georgia, serif; color: #2C2416;">
      <span style="color: #4A7C59;">Distributed</span> Readings
    </h2>
    <p style="color: #7A6B5A; font-style: italic;">
      {new_count} new article(s) fetched this week.
    </p>
    <table style="width: 100%; border-collapse: collapse;">
"""

    for a in articles:
        body_html += f"""      <tr style="border-bottom: 1px solid rgba(74,124,89,0.14);">
        <td style="padding: 10px 0;">
          <span style="font-size: 11px; background: #E8F2EC; color: #4A7C59; padding: 2px 8px; border-radius: 10px;">{a['company']}</span>
          <br>
          <a href="{a['url']}" style="color: #2C2416; text-decoration: none; font-weight: 500;">{a['title']}</a>
        </td>
      </tr>
"""

    body_html += f"""    </table>
    <p style="margin-top: 24px;">
      <a href="http://18.222.252.226" style="background: #4A7C59; color: white; padding: 8px 16px; border-radius: 8px; text-decoration: none; font-size: 13px;">
        Open Distributed Readings
      </a>
    </p>
    <p style="font-size: 11px; color: #7A6B5A; margin-top: 32px;">
      Sent automatically every Monday at 8am UTC.
    </p>
  </div>
</body>
</html>"""

    client = boto3.client("ses", region_name=AWS_REGION)
    response = client.send_email(
        Source=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Message={
            "Subject": {
                "Data": f"Distributed Readings — {new_count} new article(s) this week",
                "Charset": "UTF-8",
            },
            "Body": {
                "Text": {"Data": body_text, "Charset": "UTF-8"},
                "Html": {"Data": body_html, "Charset": "UTF-8"},
            },
        },
    )
    print(f"Email sent! Message ID: {response['MessageId']}")


if __name__ == "__main__":
    count = sys.argv[1] if len(sys.argv) > 1 else "0"
    send_email(int(count))
