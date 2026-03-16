#!/bin/bash
# Setup systemd timers for daily result checking on VPS
# Run this once on VPS: bash /opt/dlogic/linebot/scripts/setup_vps_cron.sh

LINEBOT_DIR="/opt/dlogic/linebot"
PYTHON="$LINEBOT_DIR/venv/bin/python3"

# ── dlogic-results.service ──
cat > /etc/systemd/system/dlogic-results.service << 'EOF'
[Unit]
Description=Dlogic Daily Results Checker
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/opt/dlogic/linebot
ExecStart=/opt/dlogic/linebot/venv/bin/python3 scripts/vps_cron_results.py
TimeoutSec=3600
User=root
Environment=HOME=/root
EOF

# ── dlogic-results.timer (21:30 JST daily) ──
cat > /etc/systemd/system/dlogic-results.timer << 'EOF'
[Unit]
Description=Run Dlogic daily results check at 21:30 JST

[Timer]
OnCalendar=*-*-* 12:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Note: OnCalendar uses UTC. 21:30 JST = 12:30 UTC

systemctl daemon-reload
systemctl enable dlogic-results.timer
systemctl start dlogic-results.timer

echo "=== Setup complete ==="
echo "Timer status:"
systemctl list-timers dlogic-results.timer
echo ""
echo "To run manually: systemctl start dlogic-results.service"
echo "To check logs: journalctl -u dlogic-results.service --no-pager"
echo "Or: cat /opt/dlogic/linebot/logs/cron_results_*.log"
