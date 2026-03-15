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

DLOGIC_TOP_URL = "https://www.dlogicai.in/"
MYBOT_LANDING_URL = "https://www.dlogicai.in/mybot"


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


def generate_mybot_image(output_path: str, x_account: str | None = None):
    """Generate MYBOT rich menu image (2500x1686, 2 rows x 3 columns)."""
    W, H = 2500, 1686
    COLS, ROWS = 3, 2

    cell_w = W // COLS
    cell_h = H // ROWS

    BG = "#050608"
    CARD_BG = "#0b0f12"
    ACCENT = "#f0b90b"

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    font_path = _find_font()
    if font_path:
        main_font = ImageFont.truetype(font_path, 60)
        sub_font = ImageFont.truetype(font_path, 34)
        brand_font = ImageFont.truetype(font_path, 24)
    else:
        main_font = ImageFont.load_default()
        sub_font = main_font
        brand_font = main_font

    # Row 1: JRA, 地方, お問い合わせ
    # Row 2: MYBOTとは？, X (作成者), Dlogic TOP
    x_label = f"@{x_account}" if x_account else "X"
    buttons = [
        ("JRA", "今日のJRA"),
        ("NAR", "今日の地方"),
        ("CONTACT", "お問い合わせ"),
        ("MYBOT", "MYBOTとは？"),
        ("X", x_label),
        ("SITE", "Dlogic TOP"),
    ]

    # Color map for sub labels
    sub_colors = {
        "JRA": ACCENT,
        "NAR": ACCENT,
        "CONTACT": "#06C755",
        "MYBOT": "#a855f7",
        "X": "#1DA1F2",
        "SITE": ACCENT,
    }

    for idx, (sub, label) in enumerate(buttons):
        col = idx % COLS
        row = idx // COLS
        x0 = col * cell_w
        y0 = row * cell_h
        x1 = x0 + cell_w
        y1 = y0 + cell_h

        m = 6
        draw.rectangle([x0 + m, y0 + m, x1 - m, y1 - m], fill=CARD_BG)

        # Accent bars (left + bottom)
        bar_color = sub_colors.get(sub, ACCENT)
        draw.rectangle([x0 + m, y0 + m, x0 + m + 5, y1 - m], fill=bar_color)
        draw.rectangle([x0 + m, y1 - m - 3, x1 - m, y1 - m], fill=bar_color)

        # Sub label
        sub_bbox = draw.textbbox((0, 0), sub, font=sub_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = x0 + (cell_w - sub_w) // 2
        sub_y = y0 + cell_h // 2 - 70
        draw.text((sub_x, sub_y), sub, fill=bar_color, font=sub_font)

        # Main label
        bbox = draw.textbbox((0, 0), label, font=main_font)
        tw = bbox[2] - bbox[0]
        tx = x0 + (cell_w - tw) // 2
        ty = y0 + cell_h // 2 + 5
        draw.text((tx, ty), label, fill="#ffffff", font=main_font)

    # Grid separators
    for c in range(1, COLS):
        x = c * cell_w
        draw.line([(x, 0), (x, H)], fill=ACCENT, width=3)
    draw.line([(0, cell_h), (W, cell_h)], fill=ACCENT, width=3)

    # Outer border
    draw.rectangle([0, 0, W - 1, H - 1], outline=ACCENT, width=3)

    # Brand watermark
    draw.text((W - 300, H - 36), "Powered by D-Logic", fill="#333333", font=brand_font)

    img.save(output_path, "PNG")
    return output_path


def setup_mybot_richmenu(
    access_token: str,
    x_account: str | None = None,
) -> str | None:
    """Create and deploy a MYBOT rich menu for a LINE channel.

    Returns the rich menu ID on success, None on failure.
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    # 1. Generate image
    tmp_dir = os.path.join(PROJECT_DIR, "data", "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    image_path = os.path.join(tmp_dir, "mybot_richmenu.png")
    generate_mybot_image(image_path, x_account=x_account)

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

    # 3. Create rich menu (2 rows x 3 columns)
    W, H = 2500, 1686
    cell_w = W // 3
    cell_h = H // 2

    # Build X URL
    x_url = f"https://x.com/{x_account}" if x_account else DLOGIC_TOP_URL

    menu_data = {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": "MYBOT Menu",
        "chatBarText": "メニュー",
        "areas": [
            # Row 1
            {
                "bounds": {"x": 0, "y": 0, "width": cell_w, "height": cell_h},
                "action": {"type": "message", "text": "今日のJRA"},
            },
            {
                "bounds": {"x": cell_w, "y": 0, "width": cell_w, "height": cell_h},
                "action": {"type": "message", "text": "今日の地方競馬"},
            },
            {
                "bounds": {"x": cell_w * 2, "y": 0, "width": cell_w, "height": cell_h},
                "action": {"type": "message", "text": "Dlogic運営に問い合わせ"},
            },
            # Row 2
            {
                "bounds": {"x": 0, "y": cell_h, "width": cell_w, "height": cell_h},
                "action": {"type": "uri", "uri": MYBOT_LANDING_URL},
            },
            {
                "bounds": {"x": cell_w, "y": cell_h, "width": cell_w, "height": cell_h},
                "action": {"type": "uri", "uri": x_url},
            },
            {
                "bounds": {"x": cell_w * 2, "y": cell_h, "width": cell_w, "height": cell_h},
                "action": {"type": "uri", "uri": DLOGIC_TOP_URL},
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
        print("Usage: python setup_mybot_richmenu.py <access_token> [x_account]")
        sys.exit(1)

    token = sys.argv[1]
    x_acct = sys.argv[2] if len(sys.argv) > 2 else None
    result = setup_mybot_richmenu(token, x_account=x_acct)
    if result:
        print(f"Done! Rich menu ID: {result}")
    else:
        print("Failed to setup rich menu")
        sys.exit(1)
