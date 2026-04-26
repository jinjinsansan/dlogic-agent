#!/usr/bin/env python3
"""穴党AI参謀: 起動時の過去実績紹介ポスト (一発実行)."""
import glob
import json
import logging
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anatou_telegram_lib import send_telegram, date_display, setup_logging

logger = setup_logging()
SNAPSHOT_DIR = "/opt/dlogic/linebot/data/golden_history"


def aggregate_history():
    files = sorted(glob.glob(os.path.join(SNAPSHOT_DIR, "*.json")))
    total_strict = total_hits = total_profit = 0
    days_with_strict = 0
    daily_records = []

    for f in files:
        with open(f, encoding='utf-8') as fp:
            d = json.load(fp)
        s = d.get("summary", {})
        n = s.get("strict_finished", 0)
        if n == 0:
            continue
        h = s.get("strict_hits", 0)
        p = s.get("strict_profit", 0)
        total_strict += n
        total_hits += h
        total_profit += p
        days_with_strict += 1
        daily_records.append({
            "date": d.get("date", ""),
            "weekday": d.get("weekday", ""),
            "n": n, "hits": h, "profit": p,
        })

    daily_records.sort(key=lambda x: x["profit"], reverse=True)

    return {
        "total_strict": total_strict,
        "total_hits": total_hits,
        "total_profit": total_profit,
        "days": days_with_strict,
        "top_days": daily_records[:3],
        "first_date": files[0].split("/")[-1].replace(".json", "") if files else "",
        "last_date": files[-1].split("/")[-1].replace(".json", "") if files else "",
    }


def format_intro() -> str:
    agg = aggregate_history()
    if agg["total_strict"] == 0:
        return ""

    invest = agg["total_strict"] * 100
    payout = invest + agg["total_profit"]
    recovery = payout / invest * 100 if invest else 0
    win_rate = agg["total_hits"] / agg["total_strict"] * 100 if agg["total_strict"] else 0

    period = (
        f"{date_display(agg['first_date'])} 〜 {date_display(agg['last_date'])}"
        if agg["first_date"] and agg["last_date"] else ""
    )

    lines = [
        "🎉 <b>競馬GANTZ 起動</b>",
        "<b>━━━━━━━━━━━━━━</b>",
        "",
        "あなた 達 の 馬券 は もう ない。",
        "新しい 馬券 を あげまし ょう。",
        "",
        "中穴 専門 の AI 任務を、",
        "毎日 <b>無料 配信</b> し まち。",
        "",
        "<b>━━━━━━━━━━━━━━</b>",
        f"📊 <b>過去 戦果</b> ({period})",
        "<b>━━━━━━━━━━━━━━</b>",
        "",
        "🚀 <b>信頼度・最高 (確定 任務)</b>",
        f"  出撃: <b>{agg['total_strict']}ターゲット</b>",
        f"  撃破: <b>{agg['total_hits']}件</b> ({win_rate:.1f}%)",
        f"  投資: ¥{invest:,}",
        f"  払戻: ¥{payout:,}",
        f"  報酬: <b>+¥{agg['total_profit']:,}</b>",
        f"  回収率: <b>{recovery:.1f}%</b>",
        "",
        "<b>━━━━━━━━━━━━━━</b>",
        "🔥 <b>圧倒的 戦果 TOP3</b>",
        "<b>━━━━━━━━━━━━━━</b>",
    ]

    for i, d in enumerate(agg["top_days"], 1):
        date_str = date_display(d["date"])
        lines.append(
            f"  {i}. {date_str}: {d['n']}ターゲット中 {d['hits']}撃破 → "
            f"<b>+¥{d['profit']:,}</b>"
        )

    lines.append("")
    lines.append("<b>━━━━━━━━━━━━━━</b>")
    lines.append("📝 <b>競馬GANTZ の 仕様</b>")
    lines.append("<b>━━━━━━━━━━━━━━</b>")
    lines.append("")
    lines.append("・1日 の 撃破: 0〜5回 (平均1回)")
    lines.append("・<b>27%の日 は 完全 失敗</b>")
    lines.append("・残り 73% の 日 で 報酬 獲得")
    lines.append("・上位3日 で 全期間 報酬 の 半分以上")
    lines.append("")
    lines.append("つまり:")
    lines.append("<b>「ほとんど 外し まち。1点で 全額 回収 し まち」</b>")
    lines.append("これ が 競馬GANTZ の 仕様 で だす。")
    lines.append("")
    lines.append("任務を <b>絞らずに 全部 受けて くだちい</b>。")
    lines.append("たまに 来る <b>撃破日</b> を 取り逃さない。")
    lines.append("これ が 勝つ 唯一 の 任務遂行法 で だす。")
    lines.append("")
    lines.append("<b>━━━━━━━━━━━━━━</b>")
    lines.append("⏰ <b>配信 スケジュール</b>")
    lines.append("<b>━━━━━━━━━━━━━━</b>")
    lines.append("・08:00 任務開始 + 昨日の戦果")
    lines.append("・09:00 信頼度・最高 (月-金、該当日のみ)")
    lines.append("・23:00 本日の 戦果報告")
    lines.append("")
    lines.append("📡 完全無料、いつまで 続けるか 未定。")
    lines.append("仕事を 受けて くだちい。")

    return "\n".join(lines)


def main():
    msg = format_intro()
    if not msg:
        logger.error("no history data found")
        return 1

    ok = send_telegram(msg)
    logger.info(f"intro sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
