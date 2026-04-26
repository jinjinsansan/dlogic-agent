#!/usr/bin/env python3
"""競馬GANTZ: 08:00 朝の起動 + 昨日の戦果報告 (GANTZ口調)."""
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anatou_telegram_lib import (
    fetch_pattern, send_telegram,
    date_yyyymmdd_today, date_yyyymmdd_yesterday, date_display,
    setup_logging, JST,
)

logger = setup_logging()


GREETINGS = [
    "起動 しまちた。",
    "今日も 任務を 配信 しまち。",
    "競馬GANTZ、稼働 中 です。",
    "あなた 達 の 馬券 は もう ない。新しい 馬券 を あげまし ょう。",
    "玉 が 起動 しまちた。",
]


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
    lines.append(f"📊 <b>昨日の戦果 ({yest})</b>")
    lines.append("━━━━━━━━━━━━")

    if strict_finished > 0:
        invest = strict_finished * 100
        payout = invest + strict_profit
        sign = "+" if strict_profit >= 0 else ""
        emoji = "✨" if strict_profit > 0 else "💧"
        lines.append(
            f"🚀 <b>信頼度・最高</b> {strict_finished}ターゲット 出撃 → <b>{strict_hits}撃破</b>"
        )
        lines.append(f"   投資 {invest}円 → 払戻 {payout}円")
        lines.append(f"   報酬 <b>{sign}{strict_profit}円</b> {emoji}")

    if loose_finished > 0:
        invest = loose_finished * 100
        payout = invest + loose_profit
        sign = "+" if loose_profit >= 0 else ""
        lines.append("")
        lines.append(
            f"⭐ 参考データ {loose_finished}ターゲット → {loose_hits}撃破 / {sign}{loose_profit}円"
        )

    return "\n".join(lines)


def build_message() -> str:
    yest = date_yyyymmdd_yesterday()
    yest_data = fetch_pattern(yest)

    today_disp = date_display(date_yyyymmdd_today())
    weekday_idx = datetime.now(JST).weekday()
    greeting = GREETINGS[weekday_idx % len(GREETINGS)]

    lines = [
        f"☀️ <b>{today_disp}</b>",
        "",
        greeting,
        "",
    ]

    recap = format_yesterday_recap(yest_data)
    if recap:
        lines.append(recap)
        lines.append("")
        lines.append("ほとんど 外し まち。")
        lines.append("1ターゲット で 全額 回収 し まち。")
        lines.append("それが <b>競馬GANTZ</b> の 仕様 で だす。")
    else:
        lines.append("本日も AI が 中穴を 狙って いきまち。")
        lines.append("信頼度・高 の 任務は 発走前に 配信 しまち。")

    lines.append("")
    lines.append("━━━━━━━━━━━━")
    lines.append("⏰ 09:00 信頼度・高 (該当日のみ)")
    lines.append("⏰ 23:00 本日の 戦果報告")
    lines.append("")
    lines.append("仕事を 受けて くだちい。")

    return "\n".join(lines)


def main():
    msg = build_message()
    ok = send_telegram(msg)
    logger.info(f"greet sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
