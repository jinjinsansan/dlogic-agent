#!/bin/bash
set -euo pipefail

PATH=/usr/sbin:/usr/bin:/sbin:/bin

CONFIG_LIST=/etc/wireguard/proton/configs.txt
STATE_FILE=/var/run/netkeiba-vpn-state.json
ENV_FILE=/opt/dlogic/linebot/.env.local
CHECK_URL="https://race.netkeiba.com/race/shutuba.html?race_id=202606020801"
CONNECT_TIMEOUT=8
MAX_TIME=12

if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r key val; do
    [ -z "$key" ] && continue
    case "$key" in
      \#*) continue ;;
    esac
    export "$key"="$val"
  done < "$ENV_FILE"
fi

TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-""}
ADMIN_CHAT_ID=${ADMIN_TELEGRAM_CHAT_ID:-""}

send_telegram() {
  local text="$1"
  if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$ADMIN_CHAT_ID" ]; then
    return 0
  fi
  /usr/bin/curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -H 'Content-Type: application/json' \
    -d "{\"chat_id\":\"${ADMIN_CHAT_ID}\",\"text\":\"${text}\"}" >/dev/null || true
}

if [ ! -f "$CONFIG_LIST" ]; then
  send_telegram "⚠️ VPN監視: 設定リストが見つからない (${CONFIG_LIST})"
  exit 1
fi

mapfile -t CONFIGS < "$CONFIG_LIST"
if [ ${#CONFIGS[@]} -eq 0 ]; then
  send_telegram "⚠️ VPN監視: WireGuard設定が空"
  exit 1
fi

read_state() {
  /usr/bin/python3 - <<'PY'
import json
from pathlib import Path
path = Path("/var/run/netkeiba-vpn-state.json")
if not path.exists():
    print("0 unknown")
    raise SystemExit
try:
    data = json.loads(path.read_text())
except Exception:
    print("0 unknown")
    raise SystemExit
idx = data.get("active_index", 0)
status = data.get("status", "unknown")
print(f"{idx} {status}")
PY
}

write_state() {
  local idx="$1"
  local status="$2"
  /usr/bin/python3 - <<PY
import json
from pathlib import Path
data = {"active_index": int(${idx}), "status": "${status}"}
Path("/var/run/netkeiba-vpn-state.json").write_text(json.dumps(data))
PY
}

check_url() {
  local code
  code=$(/usr/bin/curl -4 -s -o /dev/null -w "%{http_code}" \
    --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" "$CHECK_URL" || echo "000")
  if [ "$code" -ge 200 ] && [ "$code" -lt 400 ]; then
    return 0
  fi
  return 1
}

switch_to() {
  local idx="$1"
  local conf="${CONFIGS[$idx]}"
  /bin/ln -sf "$conf" /etc/wireguard/wg0.conf
  /usr/bin/systemctl restart wg-quick@wg0
  /usr/bin/systemctl restart netkeiba-routing.service
}

read -r ACTIVE_IDX LAST_STATUS <<< "$(read_state)"
if [ "$ACTIVE_IDX" -ge ${#CONFIGS[@]} ]; then
  ACTIVE_IDX=0
fi

if check_url; then
  if [ "$LAST_STATUS" != "ok" ]; then
    send_telegram "✅ VPN復旧: ${CONFIGS[$ACTIVE_IDX]}"
  fi
  write_state "$ACTIVE_IDX" "ok"
  exit 0
fi

count=${#CONFIGS[@]}
for ((i=1; i<=count; i++)); do
  next_idx=$(( (ACTIVE_IDX + i) % count ))
  switch_to "$next_idx"
  /bin/sleep 4
  if check_url; then
    send_telegram "⚠️ VPN切替: ${CONFIGS[$ACTIVE_IDX]} → ${CONFIGS[$next_idx]}"
    write_state "$next_idx" "ok"
    exit 0
  fi
done

send_telegram "🚨 VPN障害: すべての設定で接続不可"
write_state "$ACTIVE_IDX" "fail"
exit 1
