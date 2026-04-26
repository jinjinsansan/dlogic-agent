#!/usr/bin/env python3
"""競馬GANTZ: 23:00 本日の戦果報告 — GANTZ口調."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from anatou_telegram_lib import (
    fetch_pattern, send_telegram,
    date_yyyymmdd_today, date_display,
    setup_logging,
)

logger = setup_logging()


def format_results(data: dict) -> str:
    races = data.get("races", []) or []
    strict_races = [r for r in races if r.get("is_golden_strict")]
    if not strict_races:
        return ""

    today = date_display(data.get("date", ""))
    summary = data.get("summary") or {}
    finished = summary.get("strict_finished", 0)
    hits = summary.get("strict_hits", 0)
    profit = summary.get("strict_profit", 0)

    lines = [
        f"🌙 <b>本日の戦果報告</b> ({today})",
        "━━━━━━━━━━━━━━",
        "",
    ]

    strict_sorted = sorted(strict_races, key=lambda r: (r.get("start_time") or "99:99",
                                                         r.get("venue", ""),
                                                         r.get("race_number", 0)))

    for r in strict_sorted:
        cons = r.get("consensus") or {}
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        cons_horse = cons.get("horse_number", "?")
        cons_name = cons.get("horse_name", "?")
        result = r.get("result")

        lines.append(f"📍 <b>{venue} {rn}R</b>")
        lines.append(f"   ◎{cons_horse}.{cons_name}")

        if not result:
            lines.append("   → ⏳ 結果 未確定")
        else:
            winner = result.get("winner_number")
            payout = result.get("win_payout") or 0
            won = result.get("did_consensus_win")
            placed = result.get("did_consensus_place")
            top3 = result.get("top3") or []
            winner_name = ""
            for t in top3:
                if t.get("horse_number") == winner:
                    winner_name = t.get("horse_name", "")
                    break

            if won:
                lines.append(f"   → 1着: <b>{winner}番 {winner_name}</b>")
                lines.append(f"   → 単勝 <b>¥{payout:,}</b>  🎯 <b>撃破!</b>")
            elif placed:
                lines.append(f"   → 1着: {winner}番 {winner_name}")
                lines.append("   → ◎は 3着内 (撃破に 至らず)")
            else:
                lines.append(f"   → 1着: {winner}番 {winner_name}")
                lines.append("   → ✗ 失敗")
        lines.append("")

    invest = finished * 100
    payout_total = invest + profit
    sign = "+" if profit >= 0 else ""
    emoji = "✨" if profit > 0 else ("💧" if profit < 0 else "")

    lines.append("━━━━━━━━━━━━━━")
    lines.append("📊 <b>本日の 採点 (ちいてん)</b>")
    lines.append(f"  出撃: {finished}ターゲット")
    lines.append(f"  撃破: <b>{hits}件</b>")
    lines.append(f"  投資: ¥{invest:,}")
    lines.append(f"  払戻: ¥{payout_total:,}")
    lines.append(f"  報酬: <b>{sign}¥{profit:,}</b> {emoji}")
    lines.append("")

    if profit > 0:
        if hits == 1:
            lines.append("ほとんど 外し まちた。")
            lines.append("だが 1ターゲット で 全額 回収。")
            lines.append("仕様 通り の 結果 で だす。")
        elif hits >= 2:
            lines.append("複数 撃破。")
            lines.append("良い 仕事 で だす。")
        else:
            lines.append("プラス で 終了。")
    elif profit < 0:
        lines.append("今日 は 失敗 の 日 で だす。")
        lines.append("撃破 する 日 の ため に 続けて くだちい。")
        lines.append("それ だけ が 鉄則 で だす。")
    else:
        lines.append("ちょうど ±0 で だす。")

    return "\n".join(lines)


def main():
    today = date_yyyymmdd_today()
    data = fetch_pattern(today)
    if not data:
        logger.error("no data")
        return 1

    msg = format_results(data)
    if not msg:
        logger.info("no strict races today — silent")
        return 0

    ok = send_telegram(msg)
    logger.info(f"results sent={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
