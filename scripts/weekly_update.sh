#!/bin/bash
# weekly_update.sh — Fetch new articles + AI-tag them + email notification
# Runs via cron: every Monday at 8:00 AM

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

LOG_FILE="$PROJECT_DIR/data/weekly_update.log"
mkdir -p "$PROJECT_DIR/data"

echo "=== Weekly Update: $(date) ===" >> "$LOG_FILE"

# Step 1: Fetch new articles from all blogs
echo "[1/3] Fetching new articles..." >> "$LOG_FILE"
FETCH_OUTPUT=$(python3 run_fetch.py 2>&1)
echo "$FETCH_OUTPUT" >> "$LOG_FILE"

# Extract the number of new articles added
NEW_COUNT=$(echo "$FETCH_OUTPUT" | grep -oP 'Added:\s+\K\d+' || echo "0")

# Step 2: AI-tag any new (unanalyzed) articles
echo "[2/3] AI-tagging new articles..." >> "$LOG_FILE"
python3 run_ai_tag.py >> "$LOG_FILE" 2>&1

# Step 3: Send email notification (only if new articles were found)
if [ "$NEW_COUNT" -gt 0 ] 2>/dev/null; then
    echo "[3/3] Sending email notification ($NEW_COUNT new)..." >> "$LOG_FILE"
    python3 scripts/notify.py "$NEW_COUNT" >> "$LOG_FILE" 2>&1
else
    echo "[3/3] No new articles — skipping email." >> "$LOG_FILE"
fi

echo "=== Done: $(date) ===" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
