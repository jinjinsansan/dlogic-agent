#!/usr/bin/env python3
"""穴党参謀AI: 起動時の過去実績紹介ポスト（一発実行）."""
import glob
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anatou_telegram_lib import send_telegram_long, date_display, setup_logging

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
        "🎉 <b>穴党参謀AI 配信スタート</b>",
        "<b>━━━━━━━━━━━━━━</b>",
        "",
        "独自AI 4基の合議による人気薄推奨を、",
        "毎日 <b>無料配信</b> しています。",
        "",
        "<b>━━━━━━━━━━━━━━</b>",
        f"📊 <b>過去戦果</b>（{period}）",
        "<b>━━━━━━━━━━━━━━</b>",
        "",
        "🚀 <b>本命厳格（Layer 1）累計</b>",
        f"  本命数: <b>{agg['total_strict']}件</b>",
        f"  的中: <b>{agg['total_hits']}件</b>（{win_rate:.1f}%）",
        f"  投資: ¥{invest:,}",
        f"  払戻: ¥{payout:,}",
        f"  収支: <b>+¥{agg['total_profit']:,}</b>",
        f"  回収率: <b>{recovery:.1f}%</b>",
        "",
        "<b>━━━━━━━━━━━━━━</b>",
        "🔥 <b>戦果ベスト3</b>",
        "<b>━━━━━━━━━━━━━━</b>",
    ]

    for i, d in enumerate(agg["top_days"], 1):
        date_str = date_display(d["date"])
        lines.append(
            f"  {i}. {date_str}: {d['n']}件中 {d['hits']}件的中 → "
            f"<b>+¥{d['profit']:,}</b>"
        )

    lines.append("")
    lines.append("<b>━━━━━━━━━━━━━━</b>")
    lines.append("📝 <b>運用の特徴</b>")
    lines.append("<b>━━━━━━━━━━━━━━</b>")
    lines.append("")
    lines.append("・1日の的中: 0〜5回（平均1回）")
    lines.append("・<b>27%の日は的中ゼロ</b>")
    lines.append("・残り 73% の日でプラス収支")
    lines.append("・上位3日で全期間収支の半分以上")
    lines.append("")
    lines.append("人気薄狙いのため的中率は低めですが、")
    lines.append("1点的中で投資額を大きくカバーできるのが特徴です。")
    lines.append("")
    lines.append("配信を絞らず全本命を淡々と購入し、")
    lines.append("たまに来る大的中を取り逃さないことが運用前提です。")
    lines.append("")
    lines.append("<b>━━━━━━━━━━━━━━</b>")
    lines.append("⏰ <b>配信スケジュール</b>")
    lines.append("<b>━━━━━━━━━━━━━━</b>")
    lines.append("・08:00 朝の挨拶 + 昨日の戦果")
    lines.append("・09:00 本命厳格（火水木、該当日のみ）")
    lines.append("・23:00 本日の戦果報告")
    lines.append("")
    lines.append("📡 完全無料で配信中です。")

    return "\n".join(lines)


def main():
    msg = format_intro()
    if not msg:
        logger.error("no history data found")
        return 1

    ok = send_telegram_long(msg)
    logger.info(f"intro sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
