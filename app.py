"""LINE Bot webhook server + WebApp chat API — designed for Gunicorn + gevent workers."""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

from flask import Flask, request, abort, Response
from flask_cors import CORS
from linebot.v3.exceptions import InvalidSignatureError

from bot.line_handlers import handler as line_handler
from api.web_chat import bp as web_chat_bp
from api.data_api import bp as data_api_bp
from api.auth import bp as auth_bp

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)
flask_app.url_map.strict_slashes = False

# CORS for WebApp chat (allow frontend origin)
CORS(flask_app, resources={
    r"/api/*": {
        "origins": [
            "https://www.dlogicai.in",
            "https://dlogicai.in",
            "http://localhost:3000",  # dev
        ],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
    }
})

# Register WebApp chat blueprint
flask_app.register_blueprint(web_chat_bp)

# Register Data API blueprint (for dlogic-note etc.)
flask_app.register_blueprint(data_api_bp)

# Register LINE Login auth blueprint
flask_app.register_blueprint(auth_bp)

# Prefetch data directory
PREFETCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'prefetch')

# Secret admin path (unguessable)
ADMIN_SECRET = "dL9kX3mQ7vR2pW8j"

# 枠番カラー (JRA/NAR standard)
FRAME_COLORS = {
    1: ("#fff", "#333"),   # 白
    2: ("#000", "#fff"),   # 黒
    3: ("#e00", "#fff"),   # 赤
    4: ("#06f", "#fff"),   # 青
    5: ("#fc0", "#333"),   # 黄
    6: ("#0a0", "#fff"),   # 緑
    7: ("#f80", "#fff"),   # 橙
    8: ("#f6c", "#333"),   # 桃
}


@flask_app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    logger.info(f"LINE webhook: {body[:200]}")
    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        logger.error("Invalid LINE signature")
        abort(400)
    return "OK"


@flask_app.route("/health", methods=["GET"])
def health():
    return "OK"


@flask_app.route(f"/x/{ADMIN_SECRET}/races", methods=["GET"])
@flask_app.route(f"/x/{ADMIN_SECRET}/races/<date_str>", methods=["GET"])
def admin_races(date_str=None):
    """Hidden admin page: view prefetched race data for visual verification."""
    if not date_str:
        tomorrow = datetime.now() + timedelta(days=1)
        date_str = tomorrow.strftime("%Y%m%d")

    # Load prefetch JSON
    filepath = os.path.join(PREFETCH_DIR, f"races_{date_str}.json")
    if not os.path.exists(filepath):
        today = datetime.now().strftime("%Y%m%d")
        filepath = os.path.join(PREFETCH_DIR, f"races_{today}.json")
        date_str = today
        if not os.path.exists(filepath):
            return Response(
                _build_no_data_html(date_str),
                content_type="text/html; charset=utf-8",
            )

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    html = _build_races_html(data, date_str)
    return Response(html, content_type="text/html; charset=utf-8")


def _build_no_data_html(date_str):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>No Data</title></head><body style="font-family:sans-serif;padding:40px;text-align:center;">
<h2>データなし: {date_str}</h2><p><a href="/x/{ADMIN_SECRET}/races">戻る</a></p></body></html>"""


def _build_races_html(data, date_str):
    races = data.get('races', [])
    metadata = data.get('metadata', {})
    formatted_date = metadata.get('formatted_date', date_str)
    venues_count = metadata.get('venues', {})

    # Group by venue
    venue_races = {}
    for r in races:
        v = r.get('venue', '不明')
        venue_races.setdefault(v, []).append(r)

    # Sort each venue's races
    for v in venue_races:
        venue_races[v].sort(key=lambda x: x.get('race_number', 0))

    unique_venues = sorted(venue_races.keys())

    # Count issues
    total_issues = 0
    for r in races:
        horses = r.get('horses', [])
        jockeys = r.get('jockeys', [])
        if len(horses) != len(jockeys):
            total_issues += 1
        if any(not h or not str(h).strip() for h in horses):
            total_issues += 1

    status_class = "status-ok" if total_issues == 0 else "status-warn"
    status_text = "ALL OK" if total_issues == 0 else f"{total_issues} ISSUES"

    base_url = f"/x/{ADMIN_SECRET}/races"
    today = datetime.now()

    # Date nav
    date_links = []
    weekdays = ['月', '火', '水', '木', '金', '土', '日']
    for delta in range(-2, 4):
        d = today + timedelta(days=delta)
        ds = d.strftime("%Y%m%d")
        label = d.strftime("%m/%d")
        wd = weekdays[d.weekday()]
        active = " active" if ds == date_str else ""
        date_links.append(f'<a href="{base_url}/{ds}" class="date-btn{active}">{label}({wd})</a>')

    # Venue tabs
    venue_tabs = []
    for v in unique_venues:
        count = len(venue_races[v])
        venue_tabs.append(f'<a href="#{v}" class="venue-tab">{v}<span>{count}R</span></a>')

    # Race cards
    race_cards = []
    for venue_name in unique_venues:
        v_races = venue_races[venue_name]
        race_cards.append(f'<div class="venue-section" id="{venue_name}">')
        race_cards.append(f'<div class="venue-header">{venue_name} — {len(v_races)}R</div>')

        for race in v_races:
            race_cards.append(_build_race_card(race))

        race_cards.append('</div>')

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Verify {formatted_date}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, 'Hiragino Kaku Gothic ProN', 'Yu Gothic', sans-serif; background: #f5f5f5; color: #333; }}

.header {{ background: #1a1a2e; color: #fff; padding: 16px 20px; position: sticky; top: 0; z-index: 100; }}
.header h1 {{ font-size: 16px; font-weight: 600; }}
.header .sub {{ font-size: 13px; color: #aaa; margin-top: 4px; }}

.toolbar {{ background: #fff; border-bottom: 1px solid #ddd; padding: 10px 16px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; position: sticky; top: 58px; z-index: 99; }}

.date-btn {{ display: inline-block; padding: 6px 12px; background: #f0f0f0; color: #555; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: 500; }}
.date-btn.active {{ background: #e94560; color: #fff; }}
.date-btn:hover {{ background: #ddd; }}
.date-btn.active:hover {{ background: #d63050; }}

.status {{ margin-left: auto; font-size: 13px; font-weight: 700; padding: 6px 14px; border-radius: 6px; }}
.status-ok {{ background: #d4edda; color: #155724; }}
.status-warn {{ background: #f8d7da; color: #721c24; }}

.venue-nav {{ background: #fff; padding: 10px 16px; border-bottom: 1px solid #ddd; display: flex; flex-wrap: wrap; gap: 6px; }}
.venue-tab {{ display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; background: #1a1a2e; color: #fff; text-decoration: none; border-radius: 20px; font-size: 13px; }}
.venue-tab span {{ background: rgba(255,255,255,0.2); padding: 1px 6px; border-radius: 10px; font-size: 11px; }}
.venue-tab:hover {{ background: #e94560; }}

.content {{ max-width: 800px; margin: 0 auto; padding: 16px; }}

.venue-section {{ margin-bottom: 24px; }}
.venue-header {{ font-size: 18px; font-weight: 700; color: #1a1a2e; padding: 12px 0 8px; border-bottom: 3px solid #e94560; margin-bottom: 12px; }}

.race-card {{ background: #fff; border-radius: 10px; margin-bottom: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
.race-title {{ display: flex; align-items: center; padding: 10px 14px; background: #fafafa; border-bottom: 1px solid #eee; gap: 10px; }}
.race-num {{ background: #1a1a2e; color: #fff; font-size: 13px; font-weight: 700; padding: 4px 10px; border-radius: 4px; white-space: nowrap; }}
.race-name {{ font-size: 14px; font-weight: 600; flex: 1; }}
.race-meta {{ font-size: 12px; color: #888; }}
.race-status {{ font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; }}
.race-ok {{ background: #d4edda; color: #155724; }}
.race-ng {{ background: #f8d7da; color: #721c24; }}

.entry-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.entry-table th {{ background: #f8f8f8; padding: 6px 10px; text-align: left; font-size: 11px; color: #888; font-weight: 600; border-bottom: 1px solid #eee; }}
.entry-table td {{ padding: 7px 10px; border-bottom: 1px solid #f0f0f0; }}
.entry-table tr:last-child td {{ border-bottom: none; }}

.frame-badge {{ display: inline-block; width: 24px; height: 24px; line-height: 24px; text-align: center; border-radius: 4px; font-size: 12px; font-weight: 700; border: 1px solid #ccc; }}
.horse-num {{ font-weight: 700; font-size: 14px; min-width: 24px; text-align: center; }}
.horse-name {{ font-weight: 600; font-size: 14px; }}
.jockey-name {{ color: #555; }}
.warn-cell {{ color: #e00; font-weight: 700; background: #fff0f0; }}
</style>
</head>
<body>

<div class="header">
  <h1>Race Data Verification</h1>
  <div class="sub">{formatted_date} | {len(races)} races | {', '.join(f'{v} {c}R' for v, c in venues_count.items())}</div>
</div>

<div class="toolbar">
  {''.join(date_links)}
  <div class="status {status_class}">{status_text}</div>
</div>

<div class="venue-nav">
  {''.join(venue_tabs)}
</div>

<div class="content">
  {''.join(race_cards)}
</div>

</body>
</html>"""


def _build_race_card(race):
    race_num = race.get('race_number', 0)
    race_name = race.get('race_name', '?')
    distance = race.get('distance', '?')
    track_cond = race.get('track_condition', '−')
    horses = race.get('horses', [])
    jockeys = race.get('jockeys', [])
    horse_numbers = race.get('horse_numbers', [])
    posts = race.get('posts', [])

    # Check issues
    issues = []
    if len(horses) != len(jockeys):
        issues.append(f"馬{len(horses)}≠騎手{len(jockeys)}")
    if len(horses) != len(horse_numbers):
        issues.append(f"馬{len(horses)}≠番{len(horse_numbers)}")
    empty_names = sum(1 for h in horses if not h or not str(h).strip())
    if empty_names:
        issues.append(f"空馬名{empty_names}")
    empty_jockeys = sum(1 for j in jockeys if not j or not str(j).strip())
    if empty_jockeys:
        issues.append(f"空騎手{empty_jockeys}")

    if issues:
        status_html = f'<span class="race-status race-ng">{" / ".join(issues)}</span>'
    else:
        status_html = f'<span class="race-status race-ok">OK {len(horses)}頭</span>'

    # Build rows
    rows = []
    max_len = max(len(horses), len(jockeys), len(horse_numbers), 1)
    for i in range(max_len):
        h_name = horses[i] if i < len(horses) else ""
        h_num = horse_numbers[i] if i < len(horse_numbers) else 0
        j_name = jockeys[i] if i < len(jockeys) else ""
        p = posts[i] if i < len(posts) else 0

        # Frame color
        bg, fg = FRAME_COLORS.get(p, ("#eee", "#333"))
        frame_html = f'<span class="frame-badge" style="background:{bg};color:{fg}">{p}</span>'

        # Warn classes
        name_cls = ' class="warn-cell"' if (not h_name or not str(h_name).strip()) else ''
        jockey_cls = ' class="warn-cell"' if (not j_name or not str(j_name).strip()) else ''

        rows.append(
            f'<tr>'
            f'<td>{frame_html}</td>'
            f'<td class="horse-num">{h_num}</td>'
            f'<td{name_cls}><span class="horse-name">{h_name or "⚠ EMPTY"}</span></td>'
            f'<td{jockey_cls}><span class="jockey-name">{j_name or "⚠ EMPTY"}</span></td>'
            f'</tr>'
        )

    return f"""<div class="race-card">
  <div class="race-title">
    <span class="race-num">{race_num}R</span>
    <span class="race-name">{race_name}</span>
    <span class="race-meta">{distance} {track_cond}</span>
    {status_html}
  </div>
  <table class="entry-table">
    <tr><th>枠</th><th>番</th><th>馬名</th><th>騎手</th></tr>
    {''.join(rows)}
  </table>
</div>"""


# Gunicorn entry point: gunicorn app:app
app = flask_app
