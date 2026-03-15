#!/usr/bin/env python3
"""MYBOT Rich Menu setup — creates rich menu for a user's LINE Official Account.

Usage:
    Called automatically when a user connects their LINE Official Account.
    Can also be run standalone:
        python scripts/setup_mybot_richmenu.py <access_token>
"""

import os
import sys
import requests
from PIL import Image, ImageDraw, ImageFont

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPTS_DIR, '..')

API = "https://api.line.me/v2/bot"


def _find_font():
    """Find a suitable Japanese font."""
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            return fp
    return None


def generate_mybot_image(output_path: str):
    """Generate MYBOT rich menu image (2500x843, 1 row x 3 columns)."""
    W, H = 2500, 843
    COL = 3

    cell_w = W // COL

    BG = "#050608"
    CARD_BG = "#0b0f12"
    ACCENT = "#f0b90b"

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    font_path = _find_font()
    if font_path:
        main_font = ImageFont.truetype(font_path, 64)
        sub_font = ImageFont.truetype(font_path, 36)
        brand_font = ImageFont.truetype(font_path, 26)
    else:
        main_font = ImageFont.load_default()
        sub_font = main_font
        brand_font = main_font

    buttons = [
        ("JRA", "今日のJRA"),
        ("NAR", "今日の地方"),
        ("CONTACT", "お問い合わせ"),
    ]

    for idx, (sub, label) in enumerate(buttons):
        x0 = idx * cell_w
        y0 = 0
        x1 = x0 + cell_w
        y1 = H

        m = 6
        draw.rectangle([x0 + m, y0 + m, x1 - m, y1 - m], fill=CARD_BG)

        # Gold accent (left bar + bottom bar)
        draw.rectangle([x0 + m, y0 + m, x0 + m + 5, y1 - m], fill=ACCENT)
        draw.rectangle([x0 + m, y1 - m - 3, x1 - m, y1 - m], fill=ACCENT)

        # Sub label
        sub_bbox = draw.textbbox((0, 0), sub, font=sub_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = x0 + (cell_w - sub_w) // 2
        sub_y = H // 2 - 80
        draw.text((sub_x, sub_y), sub, fill=ACCENT, font=sub_font)

        # Main label
        bbox = draw.textbbox((0, 0), label, font=main_font)
        tw = bbox[2] - bbox[0]
        tx = x0 + (cell_w - tw) // 2
        ty = H // 2 + 0
        draw.text((tx, ty), label, fill="#ffffff", font=main_font)

    # Grid separators
    for c in range(1, COL):
        x = c * cell_w
        draw.line([(x, 0), (x, H)], fill=ACCENT, width=3)

    # Outer border
    draw.rectangle([0, 0, W - 1, H - 1], outline=ACCENT, width=3)

    # Brand watermark
    draw.text((W - 300, H - 38), "Powered by D-Logic", fill="#333333", font=brand_font)

    img.save(output_path, "PNG")
    return output_path


def setup_mybot_richmenu(access_token: str) -> str | None:
    """Create and deploy a MYBOT rich menu for a LINE channel.

    Returns the rich menu ID on success, None on failure.
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    # 1. Generate image
    tmp_dir = os.path.join(PROJECT_DIR, "data", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    image_path = os.path.join(tmp_dir, "mybot_richmenu.png")
    generate_mybot_image(image_path)

    # 2. Delete existing menus (clean slate for this channel)
    try:
        resp = requests.get(f"{API}/richmenu/list", headers=headers)
        if resp.status_code == 200:
            for menu in resp.json().get("richmenus", []):
                requests.delete(
                    f"{API}/richmenu/{menu['richMenuId']}", headers=headers
                )
        requests.delete(f"{API}/user/all/richmenu", headers=headers)
    except Exception:
        pass  # Non-fatal

    # 3. Create rich menu (1 row x 3 columns)
    W, H = 2500, 843
    cell_w = W // 3

    menu_data = {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": "MYBOT Menu",
        "chatBarText": "メニュー",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": cell_w, "height": H},
                "action": {"type": "message", "text": "今日のJRA"},
            },
            {
                "bounds": {"x": cell_w, "y": 0, "width": cell_w, "height": H},
                "action": {"type": "message", "text": "今日の地方競馬"},
            },
            {
                "bounds": {"x": cell_w * 2, "y": 0, "width": cell_w, "height": H},
                "action": {"type": "message", "text": "Dlogic運営に問い合わせ"},
            },
        ],
    }

    try:
        resp = requests.post(
            f"{API}/richmenu",
            headers={**headers, "Content-Type": "application/json"},
            json=menu_data,
        )
        resp.raise_for_status()
        rich_menu_id = resp.json()["richMenuId"]
    except Exception as e:
        print(f"Failed to create rich menu: {e}")
        return None

    # 4. Upload image
    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
                headers={**headers, "Content-Type": "image/png"},
                data=f,
            )
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to upload image: {e}")
        return None

    # 5. Set as default for all users of this channel
    try:
        resp = requests.post(
            f"{API}/user/all/richmenu/{rich_menu_id}",
            headers=headers,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Failed to set default menu: {e}")
        return None

    # Cleanup temp image
    try:
        os.remove(image_path)
    except Exception:
        pass

    return rich_menu_id


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python setup_mybot_richmenu.py <access_token>")
        sys.exit(1)

    token = sys.argv[1]
    result = setup_mybot_richmenu(token)
    if result:
        print(f"Done! Rich menu ID: {result}")
    else:
        print("Failed to setup rich menu")
        sys.exit(1)
