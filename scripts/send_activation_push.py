"""Send activation push notifications to 20 users who were activated but not notified."""
import os
import sys
import time
from dotenv import load_dotenv
load_dotenv("/opt/dlogic/linebot/.env.local")

from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

# IDs from the activation logs (2026-03-17 08:38-08:39)
ids = [
    "65e41c35-ec76-4475-90fe-741eef1dcdd6",
    "e0901ae3-c130-45e8-b56e-aed5acdb3d4d",
    "6127e2e6-93d8-4f49-bad2-bf4d678b5aa7",
    "d3341369-e775-465e-9f49-b39d9eff205a",
    "0fadf7ec-0220-465d-b6a3-6b527103e1a9",
    "2ff22074-f061-444d-977b-abfbaa0784f2",
    "3809e662-3b6a-413f-94e2-13150b35dac4",
    "0757a769-23d7-4379-9759-9042158b98df",
    "739ab363-f98e-459d-a7c5-f0353dfd7536",
    "c0370ad3-7bb1-4ed4-ac84-70992be1b457",
    "d5b43b69-83ba-43bb-b3bc-ffe69931d92f",
    "9cb6c2e6-6f10-40d2-9fcc-e78cec47c30a",
    "54eb4423-2eb6-4b79-a3e8-d4287da253f4",
    "ada2444f-0878-4dcd-9532-e806bee16111",
    "e397f913-2e43-4a89-add2-9c1e881c9403",
    "5a42badd-cb35-466c-ac33-c923951a749c",
    "4852a9c5-4983-4f7c-89cf-4a43e466d342",
    "7289280b-7e7f-4a5c-b15a-a3d8a131abd9",
    "98eb90b8-bfe0-472c-a500-cbf85422ed4d",
    "5d28159b-e442-4342-892b-de7426d7b8c3",
]

# Collect line_user_ids
users = []
for uid in ids:
    res = sb.table("user_profiles").select("display_name, line_user_id").eq("id", uid).limit(1).execute()
    if res.data:
        u = res.data[0]
        lid = u.get("line_user_id", "")
        if lid and not lid.startswith("login_"):
            users.append(u)
            print(f"  Found: {u['display_name']} ({lid[:10]}...)")
        else:
            print(f"  Skip (no LINE ID): {u['display_name']}")

print(f"\nTotal to notify: {len(users)}")

if "--dry-run" in sys.argv:
    print("Dry run - not sending")
    sys.exit(0)

# Send push notifications
sys.path.insert(0, "/opt/dlogic/linebot")
from bot.line_handlers import _push, get_start_quick_reply
from config import ONBOARDING_TEXT

success = 0
failed = 0
for u in users:
    try:
        _push(
            u["line_user_id"],
            "よう、待たせたな！\U0001f525\n\n"
            "お前の順番が来たぜ。今日から俺と一緒に勝ちにいこう！\n\n"
            + ONBOARDING_TEXT,
            quick_reply=get_start_quick_reply(),
        )
        success += 1
        print(f"  Sent: {u['display_name']}")
        time.sleep(0.3)  # Rate limit
    except Exception as e:
        failed += 1
        print(f"  FAILED: {u['display_name']} - {e}")

print(f"\nDone: {success} sent, {failed} failed")
