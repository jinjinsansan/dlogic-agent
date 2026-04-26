#!/usr/bin/env python3
"""競馬GANTZ: 09:00 信頼度・最高 (任務指令) — GANTZ口調."""
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anatou_telegram_lib import (
    fetch_pattern, send_telegram,
    date_yyyymmdd_today, date_display,
    setup_logging, JST,
)

logger = setup_logging()


# Weekday → expected recovery context (audit v2 + weekday_strict_search)
WEEKDAY_CONTEXT = {
    "月": {"expected": "約125-135%", "note": "1人気 or 6-8人気 の NARレース"},
    "火": {"expected": "約450%", "note": "NAR + 5強会場 + 5-8人気"},
    "水": {"expected": "約320%", "note": "NAR + 5強会場 + 5-8人気"},
    "木": {"expected": "約120-160%", "note": "NAR + 5強会場 + 5-8人気"},
    "金": {"expected": "約115-125%", "note": "NAR + 4-5人気"},
    "土": {"expected": "—", "note": "本日 任務なち"},
    "日": {"expected": "—", "note": "本日 任務なち"},
}


def format_silence(today: str, weekday: str) -> str:
    """土日 (もしくは月金で該当なし) の沈黙投稿."""
    return "\n".join([
        f"🌑 <b>{today}</b>",
        "",
        "玉 は 静か で だす。",
        "本日 任務 は あり ま せん。",
        "",
        f"<b>{weekday}曜</b> は 玉 が 動か ない 日 で だす。",
        "仕事 は 来週 月曜 から 再開 し まち。",
        "",
        "ほとんど の 日 は 仕事 が 来ない。",
        "来た 日 は 必ず 仕事 を 受けて くだちい。",
        "",
        "それ が 競馬GANTZ の 仕様 で だす。",
    ])


def format_strict(data: dict) -> str:
    races = data.get("races", []) or []
    strict = [r for r in races if r.get("is_golden_strict")]
    today = date_display(data.get("date", ""))
    weekday = data.get("weekday", "?")

    if not strict:
        # 土日: 沈黙投稿で世界観を維持
        if weekday in ("土", "日"):
            return format_silence(today, weekday)
        # 平日で strict 0件: 完全 silent
        return ""

    ctx = WEEKDAY_CONTEXT.get(weekday, {"expected": "—", "note": ""})

    lines = [
        "🔥🔥🔥 <b>本日の任務</b> 🔥🔥🔥",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        f"<b>【信頼度・最高 / {today}】</b>",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "",
        "🚨 これから ある馬を 当てて くだちい 🚨",
        "🚨 全ターゲット に <b>単勝100円</b> を 投じて くだちい 🚨",
        "",
    ]

    strict_sorted = sorted(strict, key=lambda r: r.get("start_time") or "99:99")
    for i, r in enumerate(strict_sorted, 1):
        cons = r.get("consensus") or {}
        time_str = r.get("start_time") or "—"
        pop = r.get("popularity_rank")
        pop_str = f"{pop}番人気" if pop else "?番人気"
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        hn = cons.get("horse_number", "?")
        name = cons.get("horse_name", "?")

        lines.append(f"━━━ <b>ターゲット{i}</b> ━━━")
        lines.append(f"📍 <b>{venue} {rn}R</b>  ⏰ <b>{time_str}</b>")
        lines.append(f"🐎 <b>{hn}番 {name}</b> ({pop_str})")
        lines.append(f"🎯 武器: <b>単勝 {hn}</b>")
        lines.append("")

    lines.append("<b>━━━━━━━━━━━━━━━━━━</b>")
    lines.append(f"<b>📝 全 {len(strict)}ターゲット</b> / 投資 {len(strict) * 100}円")
    lines.append("<b>━━━━━━━━━━━━━━━━━━</b>")
    lines.append("")
    lines.append("💎 <b>任務遂行ルール</b>")
    lines.append("・全ターゲット に <b>単勝100円</b> を 投じる")
    lines.append("・絞らない、足さない")
    lines.append("・外しても 続けて くだちい")
    lines.append("")
    lines.append("🔥 <b>競馬GANTZ の 仕様</b>")
    lines.append("ほとんど の ターゲット は 失敗 し まち。")
    lines.append("だが <b>1〜2 撃破 で 全体 プラス</b>。")
    lines.append('"1点で 全額 回収" が この 仕様 で だす。')
    lines.append("")
    lines.append("外して 落ち込まない こと。")
    lines.append("続ける こと だけが 鉄則 で だす。")
    lines.append("")
    lines.append(f"📈 <b>本日 ({weekday}曜) の 想定 報酬率: {ctx['expected']}</b>")
    lines.append(f"   {ctx['note']}")
    lines.append("")
    lines.append("📊 過去の 戦果 (火水木 確定 任務)")
    lines.append("出撃 114ターゲット / <b>16撃破</b> / 報酬 <b>+40,420円</b>")
    lines.append("回収率 <b>454.6%</b>")

    return "\n".join(lines)


def main():
    today = date_yyyymmdd_today()
    data = fetch_pattern(today)
    if not data:
        logger.error("no data")
        return 1

    msg = format_strict(data)
    if not msg:
        logger.info("no strict — silent")
        return 0

    ok = send_telegram(msg)
    logger.info(f"strict sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
