import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(".env.local")
from db.supabase_client import get_client

inquiry_id = int(sys.argv[1])
message = sys.argv[2]

sb = get_client()
res = sb.table("inquiries").select("line_user_id,display_name").eq("id", inquiry_id).limit(1).execute()
if not res.data:
    print(f"Inquiry #{inquiry_id} not found")
    sys.exit(1)

line_user_id = res.data[0].get("line_user_id")
user_name = res.data[0].get("display_name", "")

if line_user_id:
    from bot.line_handlers import _push, get_start_quick_reply
    msg = (
        f"おう{user_name}！運営から回答が来たぜ\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{message}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"他にも気になることがあったら気軽に言ってくれ！"
    )
    _push(line_user_id, msg, quick_reply=get_start_quick_reply())
    print(f"Push sent to {user_name}")
else:
    print("No line_user_id")
