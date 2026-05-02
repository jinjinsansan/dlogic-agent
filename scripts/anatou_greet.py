#!/usr/bin/env python3
"""穴党参謀AI: 08:00 朝の起動 + 昨日の戦果報告."""
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anatou_telegram_lib import (
    fetch_pattern, send_telegram_long,
    date_yyyymmdd_today, date_yyyymmdd_yesterday, date_display,
    setup_logging, JST,
)

logger = setup_logging()


def format_yesterday_recap(data: dict | None) -> str:
    if not data:
        return ""

    summary = data.get("summary") or {}
    strict_finished = summary.get("strict_finished", 0)
    strict_hits = summary.get("strict_hits", 0)
    strict_profit = summary.get("strict_profit", 0)
    loose_finished = summary.get("loose_finished", 0)
    loose_hits = summary.get("loose_hits", 0)
    loose_profit = summary.get("loose_profit", 0)

    if strict_finished == 0 and loose_finished == 0:
        return ""

    lines = []
    yest = date_display(data.get("date", ""))
    lines.append(f"📊 <b>昨日の戦果（{yest}）</b>")
    lines.append("━━━━━━━━━━━━")

    if strict_finished > 0:
        invest = strict_finished * 100
        payout = invest + strict_profit
        sign = "+" if strict_profit >= 0 else ""
        emoji = "✨" if strict_profit > 0 else "💧"
        recovery_pct = round(payout / invest * 100) if invest > 0 else 0
        lines.append(
            f"🎯 <b>本命厳格（Layer 1）</b> {strict_finished}件中 <b>{strict_hits}件的中</b>"
        )
        lines.append(f"   投資 {invest}円 → 払戻 {payout}円")
        lines.append(f"   収支 <b>{sign}{strict_profit}円</b>（回収率 {recovery_pct}%） {emoji}")

    if loose_finished > 0:
        invest = loose_finished * 100
        payout = invest + loose_profit
        sign = "+" if loose_profit >= 0 else ""
        lines.append("")
        lines.append(
            f"⭐ 参考データ {loose_finished}件 → {loose_hits}件的中 / 収支 {sign}{loose_profit}円"
        )

    return "\n".join(lines)


def build_message() -> str:
    yest = date_yyyymmdd_yesterday()
    yest_data = fetch_pattern(yest)

    today_disp = date_display(date_yyyymmdd_today())

    lines = [
        f"☀️ <b>{today_disp} 穴党参謀AI</b>",
        "",
        "本日の予想配信を開始します。",
        "",
    ]

    recap = format_yesterday_recap(yest_data)
    if recap:
        lines.append(recap)
        lines.append("")
        lines.append("人気薄狙いのため的中率は低めですが、")
        lines.append("1点的中で投資額をカバーする運用です。")
    else:
        lines.append("独自AI 4基の合議で本日の妙味馬を抽出します。")
        lines.append("信頼度・高の本命は発走前に配信します。")

    lines.append("")
    lines.append("━━━━━━━━━━━━")
    lines.append("⏰ 09:00 信頼度・高（該当日のみ）")
    lines.append("⏰ 23:00 本日の戦果報告")

    return "\n".join(lines)


def main():
    msg = build_message()
    ok = send_telegram_long(msg)
    logger.info(f"greet sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
