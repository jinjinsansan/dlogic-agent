import os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(".env.local")
from db.supabase_client import get_client

inquiry_id = int(sys.argv[1]) if len(sys.argv) > 1 else 14
note = sys.argv[2] if len(sys.argv) > 2 else ""

sb = get_client()
res = sb.table("inquiries").select("*").eq("id", inquiry_id).limit(1).execute()
if not res.data:
    print(f"Inquiry #{inquiry_id} not found")
    sys.exit(1)
inquiry = res.data[0]
if inquiry["status"] == "resolved":
    print(f"#{inquiry_id} is already resolved")
    sys.exit(0)

sb.table("inquiries").update({
    "status": "resolved",
    "admin_note": note or "対応済み",
    "resolved_at": datetime.now(timezone.utc).isoformat(),
}).eq("id", inquiry_id).execute()

line_user_id = inquiry.get("line_user_id")
user_name = inquiry.get("display_name", "")
notified = False
if line_user_id:
    try:
        from bot.line_handlers import _push, get_start_quick_reply
        msg = (
            f"おう{user_name}！お前の問い合わせ、運営が確認してくれたぜ！\n\n"
            "また何かあったらいつでも言ってくれ！"
        )
        _push(line_user_id, msg, quick_reply=get_start_quick_reply())
        notified = True
    except Exception as e:
        print(f"LINE notification failed: {e}")

print(f"Resolved #{inquiry_id} ({user_name}) LINE通知: {'OK' if notified else 'SKIP'}")
