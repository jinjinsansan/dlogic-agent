#!/usr/bin/env python3
"""LINE Rich Menu setup script - creates and deploys rich menu via Messaging API."""

import json
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

# ---------------------------------------------------------------------------
# Step 1: Generate Rich Menu image
# ---------------------------------------------------------------------------
def generate_image(output_path: str):
    W, H = 2500, 843
    COL, ROW = 3, 2
    cell_w = W // COL
    cell_h = H // ROW

    BG = "#050608"
    CARD_BG = "#0b0f12"
    ACCENT = "#f0b90b"

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Find Japanese font
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    font_path = None
    for fp in font_paths:
        if os.path.exists(fp):
            font_path = fp
            break

    if font_path:
        main_font = ImageFont.truetype(font_path, 56)
        sub_font = ImageFont.truetype(font_path, 32)
        brand_font = ImageFont.truetype(font_path, 26)
    else:
        main_font = ImageFont.load_default()
        sub_font = main_font
        brand_font = main_font

    buttons = [
        ("JRA",   "今日のJRA",  True),
        ("地方",   "今日の地方", True),
        ("HELP",  "使い方",     False),
        ("STATS", "俺の成績",   True),
        ("RANK",  "ランキング", True),
        ("WEB",   "サイト",     False),
    ]

    for idx, (sub, label, is_primary) in enumerate(buttons):
        col = idx % COL
        row = idx // COL
        x0 = col * cell_w
        y0 = row * cell_h
        x1 = x0 + cell_w
        y1 = y0 + cell_h

        m = 6
        draw.rectangle([x0 + m, y0 + m, x1 - m, y1 - m], fill=CARD_BG)

        # All cells get gold accent (unified design)
        draw.rectangle([x0 + m, y0 + m, x0 + m + 5, y1 - m], fill=ACCENT)
        draw.rectangle([x0 + m, y1 - m - 3, x1 - m, y1 - m], fill=ACCENT)

        sub_bbox = draw.textbbox((0, 0), sub, font=sub_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = x0 + (cell_w - sub_w) // 2
        sub_y = y0 + cell_h // 2 - 60
        draw.text((sub_x, sub_y), sub, fill=ACCENT, font=sub_font)

        bbox = draw.textbbox((0, 0), label, font=main_font)
        tw = bbox[2] - bbox[0]
        tx = x0 + (cell_w - tw) // 2
        ty = y0 + cell_h // 2 + 0
        draw.text((tx, ty), label, fill="#ffffff", font=main_font)

    # Grid separators (gold, clearly visible)
    for c in range(1, COL):
        x = c * cell_w
        draw.line([(x, 0), (x, H)], fill=ACCENT, width=3)
    draw.line([(0, cell_h), (W, cell_h)], fill=ACCENT, width=3)
    # Outer border
    draw.rectangle([0, 0, W - 1, H - 1], outline=ACCENT, width=3)

    draw.text((W - 240, H - 38), "D-Logic AI", fill="#333333", font=brand_font)

    img.save(output_path, "PNG")
    print(f"Image generated: {output_path}")


# ---------------------------------------------------------------------------
# Step 2: Delete existing rich menus
# ---------------------------------------------------------------------------
def delete_existing_menus():
    resp = requests.get(f"{API}/richmenu/list", headers=HEADERS)
    if resp.status_code == 200:
        menus = resp.json().get("richmenus", [])
        for menu in menus:
            rid = menu["richMenuId"]
            requests.delete(f"{API}/richmenu/{rid}", headers=HEADERS)
            print(f"Deleted existing menu: {rid}")
    # Also unlink default
    requests.delete(f"{API}/user/all/richmenu", headers=HEADERS)


# ---------------------------------------------------------------------------
# Step 3: Create rich menu
# ---------------------------------------------------------------------------
def create_richmenu() -> str:
    W, H = 2500, 843
    cell_w = W // 3
    cell_h = H // 2

    menu_data = {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": "D-Logic AI Menu",
        "chatBarText": "メニュー",
        "areas": [
            # Row 1
            {
                "bounds": {"x": 0, "y": 0, "width": cell_w, "height": cell_h},
                "action": {"type": "message", "text": "今日のJRA"}
            },
            {
                "bounds": {"x": cell_w, "y": 0, "width": cell_w, "height": cell_h},
                "action": {"type": "message", "text": "今日の地方競馬"}
            },
            {
                "bounds": {"x": cell_w * 2, "y": 0, "width": cell_w, "height": cell_h},
                "action": {"type": "message", "text": "ディーロジって？"}
            },
            # Row 2
            {
                "bounds": {"x": 0, "y": cell_h, "width": cell_w, "height": cell_h},
                "action": {"type": "message", "text": "俺の成績は？"}
            },
            {
                "bounds": {"x": cell_w, "y": cell_h, "width": cell_w, "height": cell_h},
                "action": {"type": "message", "text": "ランキング見せて"}
            },
            {
                "bounds": {"x": cell_w * 2, "y": cell_h, "width": cell_w, "height": cell_h},
                "action": {"type": "uri", "uri": "https://www.dlogicai.in/"}
            },
        ]
    }

    resp = requests.post(
        f"{API}/richmenu",
        headers={**HEADERS, "Content-Type": "application/json"},
        json=menu_data,
    )
    resp.raise_for_status()
    rich_menu_id = resp.json()["richMenuId"]
    print(f"Created rich menu: {rich_menu_id}")
    return rich_menu_id


# ---------------------------------------------------------------------------
# Step 4: Upload image
# ---------------------------------------------------------------------------
def upload_image(rich_menu_id: str, image_path: str):
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
            headers={**HEADERS, "Content-Type": "image/png"},
            data=f,
        )
    resp.raise_for_status()
    print(f"Image uploaded for menu: {rich_menu_id}")


# ---------------------------------------------------------------------------
# Step 5: Set as default for all users
# ---------------------------------------------------------------------------
def set_default(rich_menu_id: str):
    resp = requests.post(
        f"{API}/user/all/richmenu/{rich_menu_id}",
        headers=HEADERS,
    )
    resp.raise_for_status()
    print(f"Set as default menu: {rich_menu_id}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    image_path = os.path.join(PROJECT_DIR, "data", "richmenu.png")
    os.makedirs(os.path.dirname(image_path), exist_ok=True)

    print("=== D-Logic AI Rich Menu Setup ===")
    print()

    print("[1/5] Generating image...")
    generate_image(image_path)

    print("[2/5] Deleting existing menus...")
    delete_existing_menus()

    print("[3/5] Creating rich menu...")
    rich_menu_id = create_richmenu()

    print("[4/5] Uploading image...")
    upload_image(rich_menu_id, image_path)

    print("[5/5] Setting as default for all users...")
    set_default(rich_menu_id)

    print()
    print(f"Done! Rich menu ID: {rich_menu_id}")
    print("All LINE users will now see the menu.")


if __name__ == "__main__":
    main()
