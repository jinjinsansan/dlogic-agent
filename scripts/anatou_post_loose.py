#!/usr/bin/env python3
"""穴党参謀AI: 09:30 信頼度・低（緩いパターン）— 参考用、毎日."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anatou_telegram_lib import (
    fetch_pattern, send_telegram_long,
    date_yyyymmdd_today, date_display,
    setup_logging,
)

logger = setup_logging()


def format_loose(data: dict) -> str:
    races = data.get("races", []) or []
    # Loose minus strict (strict already posted at 09:00)
    loose_only = [
        r for r in races
        if r.get("is_golden_loose") and not r.get("is_golden_strict")
    ]
    if not loose_only:
        return ""

    today = date_display(data.get("date", ""))

    lines = [
        f"⭐ <b>{today} 穴党参謀AI 参考レース</b>",
        "━━━━━━━━━━━━",
        "<b>【信頼度・低】</b>※ 参考用",
        "━━━━━━━━━━━━",
        "",
        "<i>こちらは「見るだけ」もOKです。</i>",
        "<i>全買い不要、参考までにご確認ください。</i>",
        "",
    ]

    loose_sorted = sorted(loose_only, key=lambda r: r.get("start_time") or "99:99")
    for r in loose_sorted:
        cons = r.get("consensus") or {}
        time_str = r.get("start_time") or "—"
        pop = r.get("popularity_rank")
        pop_str = f"{pop}人気" if pop else "?人気"
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        hn = cons.get("horse_number", "?")
        name = cons.get("horse_name", "?")
        lines.append(f"📍 {venue} {rn}R ⏰{time_str}  →  {hn}.{name} ({pop_str})")

    lines.append("")
    lines.append("━━━━━━━━━━━━")
    lines.append(f"全 {len(loose_only)}レース")
    lines.append("")
    lines.append("💡 <b>使い方</b>")
    lines.append("・「信頼度・高」は全本命購入推奨")
    lines.append("・「信頼度・低」は<b>参考まで</b>")
    lines.append("・余裕があれば狙いを絞って購入してください")

    return "\n".join(lines)


def main():
    today = date_yyyymmdd_today()
    data = fetch_pattern(today)
    if not data:
        logger.error("no data")
        return 1

    msg = format_loose(data)
    if not msg:
        logger.info("no loose — silent")
        return 0

    ok = send_telegram_long(msg)
    logger.info(f"loose sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
