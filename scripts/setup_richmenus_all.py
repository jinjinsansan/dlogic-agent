#!/usr/bin/env python3
"""Create 3 rich menus (normal / waitlist / maintenance) and save IDs to .env.local."""

import os
import sys
import requests
from PIL import Image, ImageDraw, ImageFont

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPTS_DIR, '..')

# Load .env.local
env_path = os.path.join(PROJECT_DIR, '.env.local')
if os.path.exists(env_path):
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
if not TOKEN:
    print("ERROR: LINE_CHANNEL_ACCESS_TOKEN not set")
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {TOKEN}"}
API = "https://api.line.me/v2/bot"

W, H = 2500, 843
COLS, ROWS = 3, 2
CELL_W = W // COLS
CELL_H = H // ROWS


def _find_font():
    for fp in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
    ]:
        if os.path.exists(fp):
            return fp
    return None


def _load_fonts():
    fp = _find_font()
    if fp:
        return ImageFont.truetype(fp, 56), ImageFont.truetype(fp, 32), ImageFont.truetype(fp, 26)
    d = ImageFont.load_default()
    return d, d, d


def _draw_button(draw, idx, sub, label, accent, main_font, sub_font):
    col = idx % COLS
    row = idx // COLS
    x0, y0 = col * CELL_W, row * CELL_H
    x1, y1 = x0 + CELL_W, y0 + CELL_H

    m = 6
    draw.rectangle([x0 + m, y0 + m, x1 - m, y1 - m], fill="#0b0f12")
    draw.rectangle([x0 + m, y0 + m, x0 + m + 5, y1 - m], fill=accent)
    draw.rectangle([x0 + m, y1 - m - 3, x1 - m, y1 - m], fill=accent)

    sub_bbox = draw.textbbox((0, 0), sub, font=sub_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    draw.text((x0 + (CELL_W - sub_w) // 2, y0 + CELL_H // 2 - 60), sub, fill=accent, font=sub_font)

    bbox = draw.textbbox((0, 0), label, font=main_font)
    tw = bbox[2] - bbox[0]
    draw.text((x0 + (CELL_W - tw) // 2, y0 + CELL_H // 2), label, fill="#ffffff", font=main_font)


def _draw_merged_cell(draw, row, label, sub, accent, main_font, sub_font):
    """Draw a full-width merged cell in the given row (0 or 1) with the same style as buttons."""
    y0 = row * CELL_H
    y1 = y0 + CELL_H
    m = 6
    # Background
    draw.rectangle([m, y0 + m, W - m, y1 - m], fill="#0b0f12")
    # Left accent bar
    draw.rectangle([m, y0 + m, m + 5, y1 - m], fill=accent)
    # Bottom accent bar
    draw.rectangle([m, y1 - m - 3, W - m, y1 - m], fill=accent)

    if sub:
        sub_bbox = draw.textbbox((0, 0), sub, font=sub_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        draw.text(((W - sub_w) // 2, y0 + CELL_H // 2 - 60), sub, fill=accent, font=sub_font)

    bbox = draw.textbbox((0, 0), label, font=main_font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, y0 + CELL_H // 2 - (0 if sub else 15)), label, fill="#ffffff", font=main_font)


def _draw_grid(draw, accent, brand_font, merged_row=None):
    """Draw grid lines. merged_row: 0 or 1 to skip column lines in that row."""
    for c in range(1, COLS):
        if merged_row == 0:
            # Only draw column lines in bottom row
            draw.line([(c * CELL_W, CELL_H), (c * CELL_W, H)], fill=accent, width=3)
        elif merged_row == 1:
            # Only draw column lines in top row
            draw.line([(c * CELL_W, 0), (c * CELL_W, CELL_H)], fill=accent, width=3)
        else:
            draw.line([(c * CELL_W, 0), (c * CELL_W, H)], fill=accent, width=3)
    draw.line([(0, CELL_H), (W, CELL_H)], fill=accent, width=3)
    draw.rectangle([0, 0, W - 1, H - 1], outline=accent, width=3)
    draw.text((W - 240, H - 38), "D-Logic AI", fill="#333333", font=brand_font)


# ---------------------------------------------------------------------------
# Normal menu (same as current)
# ---------------------------------------------------------------------------
def generate_normal_image(path):
    main_font, sub_font, brand_font = _load_fonts()
    img = Image.new("RGB", (W, H), "#050608")
    draw = ImageDraw.Draw(img)
    buttons = [
        ("JRA", "今日のJRA"),
        ("地方", "今日の地方"),
        ("HELP", "使い方"),
        ("STATS", "俺の成績"),
        ("RANK", "ランキング"),
        ("CONTACT", "問い合わせ"),
    ]
    for i, (sub, label) in enumerate(buttons):
        _draw_button(draw, i, sub, label, "#f0b90b", main_font, sub_font)
    _draw_grid(draw, "#f0b90b", brand_font)
    img.save(path, "PNG")


def create_normal_menu():
    menu_data = {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": "D-Logic Normal Menu",
        "chatBarText": "メニュー",
        "areas": [
            {"bounds": {"x": 0, "y": 0, "width": CELL_W, "height": CELL_H},
             "action": {"type": "message", "text": "今日のJRA"}},
            {"bounds": {"x": CELL_W, "y": 0, "width": CELL_W, "height": CELL_H},
             "action": {"type": "message", "text": "今日の地方競馬"}},
            {"bounds": {"x": CELL_W * 2, "y": 0, "width": CELL_W, "height": CELL_H},
             "action": {"type": "message", "text": "ディーロジって？"}},
            {"bounds": {"x": 0, "y": CELL_H, "width": CELL_W, "height": CELL_H},
             "action": {"type": "message", "text": "俺の成績は？"}},
            {"bounds": {"x": CELL_W, "y": CELL_H, "width": CELL_W, "height": CELL_H},
             "action": {"type": "message", "text": "ランキング見せて"}},
            {"bounds": {"x": CELL_W * 2, "y": CELL_H, "width": CELL_W, "height": CELL_H},
             "action": {"type": "message", "text": "問い合わせしたい"}},
        ],
    }
    return menu_data


# ---------------------------------------------------------------------------
# Waitlist menu (full-screen single panel)
# ---------------------------------------------------------------------------
def generate_waitlist_image(path):
    main_font, sub_font, brand_font = _load_fonts()
    img = Image.new("RGB", (W, H), "#050608")
    draw = ImageDraw.Draw(img)
    accent = "#f0b90b"

    # Full-screen single panel
    m = 6
    draw.rectangle([m, m, W - m, H - m], fill="#0b0f12")
    draw.rectangle([m, m, m + 5, H - m], fill=accent)
    draw.rectangle([m, H - m - 3, W - m, H - m], fill=accent)
    draw.rectangle([0, 0, W - 1, H - 1], outline=accent, width=3)

    # Sub text
    sub = "WAITLIST"
    sub_bbox = draw.textbbox((0, 0), sub, font=sub_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    draw.text(((W - sub_w) // 2, H // 2 - 100), sub, fill=accent, font=sub_font)

    # Main text
    title = "もうすぐご案内できます"
    bbox = draw.textbbox((0, 0), title, font=main_font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, H // 2 - 30), title, fill="#ffffff", font=main_font)

    # Sub message
    msg = "お待ちください"
    bbox2 = draw.textbbox((0, 0), msg, font=sub_font)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(((W - tw2) // 2, H // 2 + 50), msg, fill=accent, font=sub_font)

    draw.text((W - 240, H - 38), "D-Logic AI", fill="#333333", font=brand_font)
    img.save(path, "PNG")


def create_waitlist_menu():
    menu_data = {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": "D-Logic Waitlist Menu",
        "chatBarText": "メニュー",
        "areas": [
            {"bounds": {"x": 0, "y": 0, "width": W, "height": H},
             "action": {"type": "message", "text": "順番待ち状況"}},
        ],
    }
    return menu_data


# ---------------------------------------------------------------------------
# Maintenance menu (full-screen single panel)
# ---------------------------------------------------------------------------
def generate_maintenance_image(path):
    main_font, sub_font, brand_font = _load_fonts()
    img = Image.new("RGB", (W, H), "#050608")
    draw = ImageDraw.Draw(img)
    accent = "#ef4444"

    # Full-screen single panel
    m = 6
    draw.rectangle([m, m, W - m, H - m], fill="#0b0f12")
    draw.rectangle([m, m, m + 5, H - m], fill=accent)
    draw.rectangle([m, H - m - 3, W - m, H - m], fill=accent)
    draw.rectangle([0, 0, W - 1, H - 1], outline=accent, width=3)

    # Sub text
    sub = "MAINTENANCE"
    sub_bbox = draw.textbbox((0, 0), sub, font=sub_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    draw.text(((W - sub_w) // 2, H // 2 - 100), sub, fill=accent, font=sub_font)

    # Main text
    title = "メンテナンス中"
    bbox = draw.textbbox((0, 0), title, font=main_font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, H // 2 - 30), title, fill="#ffffff", font=main_font)

    # Sub message
    msg = "復旧までしばらくお待ちください"
    bbox2 = draw.textbbox((0, 0), msg, font=sub_font)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(((W - tw2) // 2, H // 2 + 50), msg, fill=accent, font=sub_font)

    draw.text((W - 240, H - 38), "D-Logic AI", fill="#333333", font=brand_font)
    img.save(path, "PNG")


def create_maintenance_menu():
    menu_data = {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": "D-Logic Maintenance Menu",
        "chatBarText": "メニュー",
        "areas": [
            {"bounds": {"x": 0, "y": 0, "width": W, "height": H},
             "action": {"type": "message", "text": "メンテナンス状況"}},
        ],
    }
    return menu_data


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def api_create_menu(menu_data: dict) -> str:
    resp = requests.post(
        f"{API}/richmenu",
        headers={**HEADERS, "Content-Type": "application/json"},
        json=menu_data,
    )
    resp.raise_for_status()
    return resp.json()["richMenuId"]


def api_upload_image(menu_id: str, image_path: str):
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"https://api-data.line.me/v2/bot/richmenu/{menu_id}/content",
            headers={**HEADERS, "Content-Type": "image/png"},
            data=f,
        )
    resp.raise_for_status()


def api_set_default(menu_id: str):
    resp = requests.post(f"{API}/user/all/richmenu/{menu_id}", headers=HEADERS)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    tmp_dir = os.path.join(PROJECT_DIR, "data", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # Delete ALL existing menus first
    print("[0] Deleting all existing menus...")
    resp = requests.get(f"{API}/richmenu/list", headers=HEADERS)
    if resp.status_code == 200:
        for menu in resp.json().get("richmenus", []):
            rid = menu["richMenuId"]
            requests.delete(f"{API}/richmenu/{rid}", headers=HEADERS)
            print(f"  Deleted: {rid} ({menu.get('name', '')})")
    requests.delete(f"{API}/user/all/richmenu", headers=HEADERS)

    results = {}

    # --- Normal ---
    print("\n[1] Normal menu...")
    img_path = os.path.join(tmp_dir, "richmenu_normal.png")
    generate_normal_image(img_path)
    menu_id = api_create_menu(create_normal_menu())
    api_upload_image(menu_id, img_path)
    api_set_default(menu_id)
    results["RICHMENU_NORMAL_ID"] = menu_id
    print(f"  Created & set as default: {menu_id}")

    # --- Waitlist ---
    print("\n[2] Waitlist menu...")
    img_path = os.path.join(tmp_dir, "richmenu_waitlist.png")
    generate_waitlist_image(img_path)
    menu_id = api_create_menu(create_waitlist_menu())
    api_upload_image(menu_id, img_path)
    results["RICHMENU_WAITLIST_ID"] = menu_id
    print(f"  Created: {menu_id}")

    # --- Maintenance ---
    print("\n[3] Maintenance menu...")
    img_path = os.path.join(tmp_dir, "richmenu_maintenance.png")
    generate_maintenance_image(img_path)
    menu_id = api_create_menu(create_maintenance_menu())
    api_upload_image(menu_id, img_path)
    results["RICHMENU_MAINTENANCE_ID"] = menu_id
    print(f"  Created: {menu_id}")

    # --- Save to .env.local ---
    print("\n[4] Saving IDs to .env.local...")
    env_lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            env_lines = f.readlines()

    # Remove old RICHMENU_ lines
    env_lines = [l for l in env_lines if not l.strip().startswith("RICHMENU_")]

    # Append new
    env_lines.append("\n# Rich Menu IDs (auto-generated)\n")
    for key, val in results.items():
        env_lines.append(f"{key}={val}\n")

    with open(env_path, 'w') as f:
        f.writelines(env_lines)

    print("\n=== Done ===")
    for key, val in results.items():
        print(f"  {key}={val}")
    print("\nNormal menu is set as default for all users.")
    print("Copy these IDs to VPS .env.local as well.")


if __name__ == "__main__":
    main()
