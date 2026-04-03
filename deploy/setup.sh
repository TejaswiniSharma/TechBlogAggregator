#!/bin/bash
# setup.sh — Run this on a fresh EC2 Ubuntu 22.04 instance
# Usage: ssh into EC2, then: bash setup.sh
set -e

echo "=== [1/7] System packages ==="
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv nginx git
# Playwright browser dependencies
sudo apt install -y libgbm1 libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libatspi2.0-0

echo "=== [2/7] Clone repo ==="
cd /home/ubuntu
git clone https://github.com/TejaswiniSharma/TechBlogAggregator.git
cd TechBlogAggregator

echo "=== [3/7] Python virtualenv ==="
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

echo "=== [4/7] Initialize database ==="
mkdir -p data
python3 run_fetch.py

echo "=== [5/7] Gunicorn systemd service ==="
sudo cp deploy/techblog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable techblog
sudo systemctl start techblog

echo "=== [6/7] Nginx ==="
sudo cp deploy/nginx-techblog /etc/nginx/sites-available/techblog
sudo ln -sf /etc/nginx/sites-available/techblog /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "=== [7/7] Permissions ==="
sudo usermod -aG www-data ubuntu
chmod 755 /home/ubuntu
chmod 755 /home/ubuntu/TechBlogAggregator

echo ""
echo "=== DONE ==="
echo "Visit http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4) in your browser"
echo ""
echo "REMAINING MANUAL STEPS:"
echo "  1. Set your API key:  echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc && source ~/.bashrc"
echo "  2. Run AI tagger:     cd ~/TechBlogAggregator && source venv/bin/activate && python3 run_ai_tag.py"
echo "  3. Add weekly cron:   crontab -e, then add:"
echo "     ANTHROPIC_API_KEY=sk-ant-..."
echo "     0 8 * * 1 cd /home/ubuntu/TechBlogAggregator && PATH=/home/ubuntu/TechBlogAggregator/venv/bin:\$PATH bash scripts/weekly_update.sh >> data/cron.log 2>&1"
echo ""
echo "  4. (Optional) Add swap for memory safety:"
echo "     sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
