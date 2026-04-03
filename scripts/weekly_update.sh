#!/bin/bash
# weekly_update.sh — Fetch new articles + AI-tag them
# Runs via cron: every Monday at 8:00 AM

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

LOG_FILE="$PROJECT_DIR/data/weekly_update.log"
mkdir -p "$PROJECT_DIR/data"

echo "=== Weekly Update: $(date) ===" >> "$LOG_FILE"

# Step 1: Fetch new articles from all blogs
echo "[1/2] Fetching new articles..." >> "$LOG_FILE"
python3 run_fetch.py >> "$LOG_FILE" 2>&1

# Step 2: AI-tag any new (unanalyzed) articles
echo "[2/2] AI-tagging new articles..." >> "$LOG_FILE"
python3 run_ai_tag.py >> "$LOG_FILE" 2>&1

echo "=== Done: $(date) ===" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
