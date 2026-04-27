#!/usr/bin/env python3
"""競馬GANTZ: 23:00 本日の戦果報告 v5 — 3層 (ピンポイント / 最高 / 高) 対応."""
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


def _race_outcome_line(r: dict, prefix: str = "") -> list:
    """1レース分の結果行を生成."""
    cons = r.get("consensus") or {}
    venue = r.get("venue", "")
    rn = r.get("race_number", 0)
    cons_horse = cons.get("horse_number", "?")
    cons_name = cons.get("horse_name", "?")
    result = r.get("result")

    lines = [f"{prefix}📍 <b>{venue} {rn}R</b> ◎{cons_horse}.{cons_name}"]
    if not result:
        lines.append(f"{prefix}   → ⏳ 結果 未確定")
        return lines

    winner = result.get("winner_number")
    payout = result.get("win_payout") or 0
    won = result.get("did_consensus_win")
    top3 = result.get("top3") or []
    winner_name = ""
    for t in top3:
        if t.get("horse_number") == winner:
            winner_name = t.get("horse_name", "")
            break

    if won:
        lines.append(f"{prefix}   → 1着: <b>{winner}番 {winner_name}</b>  単勝 <b>¥{payout:,}</b>  🎯 <b>撃破!</b>")
    else:
        lines.append(f"{prefix}   → 1着: {winner}番 {winner_name}  ✗ 失敗")
    return lines


def format_v5_results(data: dict) -> str:
    races = data.get("races", []) or []
    pinpoint_races = [r for r in races if r.get("pinpoint")]
    strict_races = [r for r in races if r.get("is_golden_strict")]
    high_races = [r for r in races if r.get("is_golden_high")]

    if not pinpoint_races and not strict_races and not high_races:
        return ""  # 沈黙

    today = date_display(data.get("date", ""))
    summary = data.get("summary") or {}

    pp_finished = summary.get("pinpoint_finished", 0)
    pp_hits = summary.get("pinpoint_hits", 0)
    pp_profit = summary.get("pinpoint_profit", 0)
    s_finished = summary.get("strict_finished", 0)
    s_hits = summary.get("strict_hits", 0)
    s_profit = summary.get("strict_profit", 0)
    h_finished = summary.get("high_finished", 0)
    h_hits = summary.get("high_hits", 0)
    h_profit = summary.get("high_profit", 0)

    lines = [
        f"🌙 <b>本日の戦果報告</b> ({today})",
        "<b>━━━━━━━━━━━━━━</b>",
        "",
    ]

    pinpoint_ids = {r.get("race_id") for r in pinpoint_races}
    strict_ids = {r.get("race_id") for r in strict_races}

    # 1. Pinpoint (個別)
    if pinpoint_races:
        lines.append("🌟 <b>ピンポイント特異点</b>")
        for r in sorted(pinpoint_races, key=lambda x: (x.get("start_time") or "99", x.get("venue",""))):
            lines.extend(_race_outcome_line(r))
        lines.append("")

    # 2. Strict 個別 (ピンポイント除外)
    s_only = [r for r in strict_races if r.get("race_id") not in pinpoint_ids]
    if s_only:
        lines.append("🚀 <b>信頼度・最高</b>")
        for r in sorted(s_only, key=lambda x: (x.get("start_time") or "99", x.get("venue",""))):
            lines.extend(_race_outcome_line(r))
        lines.append("")

    # 3. High サマリ (重複除外)
    h_only = [r for r in high_races if r.get("race_id") not in (pinpoint_ids | strict_ids)]
    if h_only:
        h_only_hits = sum(1 for r in h_only if r.get("result") and r["result"].get("did_consensus_win"))
        h_only_payout = sum(
            (r["result"].get("win_payout") or 0)
            for r in h_only
            if r.get("result") and r["result"].get("did_consensus_win")
        )
        h_only_invest = len(h_only) * 100
        h_only_profit = h_only_payout - h_only_invest
        lines.append(f"✅ <b>信頼度・高 (サマリ)</b>")
        lines.append(f"   {len(h_only)}レース → {h_only_hits}撃破 / 収支 <b>¥{h_only_profit:+,}</b>")
        # 当たったやつだけ抜粋表示
        winners = [r for r in h_only if r.get("result") and r["result"].get("did_consensus_win")]
        if winners:
            lines.append("   🎯 撃破レース:")
            for r in sorted(winners, key=lambda x: x.get("venue","")):
                cons = r.get("consensus") or {}
                payout = r["result"].get("win_payout") or 0
                lines.append(f"     - {r.get('venue','')} {r.get('race_number',0)}R "
                             f"◎{cons.get('horse_number','?')}.{cons.get('horse_name','?')} → ¥{payout:,}")
        lines.append("")

    # Summary
    total_invest = (pp_finished + s_finished + h_finished) * 100
    total_payout = total_invest + pp_profit + s_profit + h_profit
    total_hits = pp_hits + s_hits + h_hits
    total_finished = pp_finished + s_finished + h_finished
    total_profit = pp_profit + s_profit + h_profit

    lines.append("<b>━━━━━━━━━━━━━━</b>")
    lines.append("📊 <b>本日の 採点 (ちいてん)</b>")
    if pp_finished:
        sign = "+" if pp_profit >= 0 else ""
        lines.append(f"  🌟 ピンポイント: {pp_finished}R / {pp_hits}撃破 / <b>¥{sign}{pp_profit:,}</b>")
    if s_finished:
        sign = "+" if s_profit >= 0 else ""
        lines.append(f"  🚀 最高: {s_finished}R / {s_hits}撃破 / <b>¥{sign}{s_profit:,}</b>")
    if h_finished:
        sign = "+" if h_profit >= 0 else ""
        lines.append(f"  ✅ 高:   {h_finished}R / {h_hits}撃破 / <b>¥{sign}{h_profit:,}</b>")
    lines.append(f"  ━━━━━━━━━")
    sign = "+" if total_profit >= 0 else ""
    emoji = "✨" if total_profit > 0 else ("💧" if total_profit < 0 else "")
    lines.append(f"  合計: {total_finished}R / {total_hits}撃破 / 収支 <b>¥{sign}{total_profit:,}</b> {emoji}")
    lines.append("")

    if total_profit > 0:
        if total_hits == 1:
            lines.append("ほとんど 外し まちた。")
            lines.append("だが 1ターゲット で 全額 回収。")
            lines.append("仕様 通り の 結果 で だす。")
        elif total_hits >= 2:
            lines.append("複数 撃破。良い 仕事 で だす。")
        else:
            lines.append("プラス で 終了。")
    elif total_profit < 0:
        lines.append("今日 は 失敗 の 日 で だす。")
        lines.append("撃破 する 日 の ため に 続けて くだちい。")
    else:
        lines.append("ちょうど ±0 で だす。")

    return "\n".join(lines)


def main():
    today = date_yyyymmdd_today()
    data = fetch_pattern(today)
    if not data:
        logger.error("no data")
        return 1

    msg = format_v5_results(data)
    if not msg:
        logger.info("no signals today — silent")
        return 0

    ok = send_telegram(msg)
    logger.info(f"results v5 sent={ok}")
    return 0 if ok else 1


# Backward compatibility
def format_results(data: dict) -> str:
    return format_v5_results(data)


if __name__ == "__main__":
    sys.exit(main())
