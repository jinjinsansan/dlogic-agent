#!/usr/bin/env python3
"""競馬GANTZ: 23:00 戦果報告 v6 — Layer 1 (NAR本命厳格) のみ.

100円単位で正直に当落報告。当たっても外れても全レース結果を公開。
"""
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


def _race_outcome_line(r: dict) -> list:
    cons = r.get("consensus") or {}
    venue = r.get("venue", "")
    rn = r.get("race_number", 0)
    cons_horse = cons.get("horse_number", "?")
    cons_name = cons.get("horse_name", "?")
    pop = r.get("popularity_rank")
    pop_str = f"{pop}人気" if pop else "?"
    result = r.get("result")

    head = f"📍 <b>{venue} {rn}R</b> ◎{cons_horse}.{cons_name} ({pop_str})"
    if not result:
        return [head, "   → ⏳ 結果 未確定"]

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
        return [head, f"   → 1着: <b>{winner}番 {winner_name}</b>  単勝 <b>¥{payout:,}</b>  🎯 <b>撃破!</b>"]
    return [head, f"   → 1着: {winner}番 {winner_name}  ✗ 失敗"]


def format_silence_results(today: str) -> str:
    return "\n".join([
        f"🌙 <b>{today} 戦果報告</b>",
        "",
        "本日 は 任務 が あり ま せん で した。",
        "",
        "条件 厳格 で だす。",
        "該当 し ない 日 こそ 規律 で だす。",
    ])


def _obihiro_result_lines(races: list) -> list:
    """Layer 2 (帯広中穴) の結果行を生成。"""
    lines = []
    for r in sorted(races, key=lambda x: (x.get("start_time") or "99")):
        rn = r.get("race_number", 0)
        result = r.get("result") or {}
        top3_list = result.get("top3") or []
        top3_nums = [t.get("horse_number") for t in top3_list]
        obihiro_outcomes = result.get("obihiro_outcomes") or []

        lines.append(f"📍 <b>帯広 {rn}R</b>")
        if not result:
            lines.append("   → ⏳ 結果 未確定")
            continue
        for oc in obihiro_outcomes:
            hn = oc.get("horse_number", "?")
            placed = oc.get("placed", False)
            fp = oc.get("fukusho_payout") or 0
            if placed:
                payout_str = f" 複勝 ¥{fp:,}" if fp else " 複勝 ✓(払戻額不明)"
                lines.append(f"   🐴 <b>{hn}番</b> → 3着内入着{payout_str} ✅")
            else:
                lines.append(f"   🐴 <b>{hn}番</b> → 着外 ✗")
    return lines


def _jra_result_lines(races: list) -> list:
    """Layer 3 (JRA S級) の結果行を生成。"""
    lines = []
    for r in sorted(races, key=lambda x: (x.get("start_time") or "99")):
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        result = r.get("result") or {}
        f5_outcomes = result.get("f5_outcomes") or []
        l3_combo_hit = result.get("l3_combo_hit", False)
        top3_list = result.get("top3") or []

        lines.append(f"📍 <b>{venue} {rn}R</b>")
        if not result:
            lines.append("   → ⏳ 結果 未確定")
            continue

        # F5複勝
        for oc in f5_outcomes:
            hn = oc.get("horse_number", "?")
            placed = oc.get("placed", False)
            fp = oc.get("fukusho_payout") or 0
            if placed:
                payout_str = f" 複勝 ¥{fp:,}" if fp else " 複勝 ✓"
                lines.append(f"   💎 F5 <b>{hn}番</b>{payout_str} ✅")
            else:
                lines.append(f"   💎 F5 <b>{hn}番</b> → 着外 ✗")

        # U2/S1
        top3_nums = [str(t.get("horse_number", "")) for t in top3_list[:3]]
        combo_str = "-".join(top3_nums) if top3_nums else "?"
        if l3_combo_hit:
            lines.append(f"   🎯 U2/S1 {combo_str} → 三連複 的中 ✅")
        else:
            actual = "-".join(str(t.get("horse_number", "?")) for t in top3_list[:3]) if top3_list else "?"
            lines.append(f"   🎯 U2/S1 → 外れ (実際の1-3着: {actual})")
    return lines


def format_v6_results(data: dict) -> str:
    races = data.get("races", []) or []
    strict_races = [r for r in races if r.get("is_golden_strict")]
    # Layer 2 (帯広) は 2026-04-27 無効化
    obihiro_races: list = []  # [r for r in races if r.get("is_layer2_obihiro")]
    jra_races = [r for r in races if r.get("is_layer3_jra_f5") or r.get("is_layer3_jra_combo")]

    today = date_display(data.get("date", ""))

    if not strict_races and not obihiro_races and not jra_races:
        return format_silence_results(today)

    summary = data.get("summary") or {}
    s_finished = summary.get("strict_finished", 0)
    s_hits = summary.get("strict_hits", 0)
    s_profit = summary.get("strict_profit", 0)

    lines = [
        f"🌙 <b>{today} 戦果報告</b>",
        "<b>━━━━━━━━━━━━━━</b>",
        "",
    ]

    # Layer 1
    if strict_races:
        lines.append("🎯 <b>Layer 1 — NAR本命厳格 結果</b>")
        lines.append("")
        for r in sorted(strict_races, key=lambda x: (x.get("start_time") or "99", x.get("venue", ""))):
            lines.extend(_race_outcome_line(r))
        lines.append("")
        invest = s_finished * 100
        payout = invest + s_profit
        sign = "+" if s_profit >= 0 else ""
        emoji = "✨" if s_profit > 0 else ("💧" if s_profit < 0 else "")
        lines.append(f"  ターゲット: {s_finished}件 / 撃破: {s_hits}件")
        lines.append(f"  収支: <b>¥{sign}{s_profit:,}</b> (投資¥{invest:,}→払戻¥{payout:,}) {emoji}")
        lines.append("")

    # Layer 2 (帯広中穴)
    if obihiro_races:
        lines.append("<b>━━━━━━━━━━━━━━</b>")
        lines.append("🟣 <b>Layer 2 — 帯広中穴 結果</b>")
        lines.append("")
        lines.extend(_obihiro_result_lines(obihiro_races))
        ob_finished = summary.get("obihiro_finished", 0)
        ob_hits = summary.get("obihiro_place_hits", 0)
        if ob_finished:
            lines.append(f"  複勝: {ob_finished}頭 / 入着: {ob_hits}頭")
        lines.append("")

    # Layer 3 (JRA S級)
    if jra_races:
        lines.append("<b>━━━━━━━━━━━━━━</b>")
        lines.append("🔵 <b>Layer 3 — JRA S級 結果</b>")
        lines.append("")
        lines.extend(_jra_result_lines(jra_races))
        f5_finished = summary.get("jra_f5_finished", 0)
        f5_hits = summary.get("jra_f5_place_hits", 0)
        combo_finished = summary.get("jra_combo_finished", 0)
        combo_hits = summary.get("jra_combo_hits", 0)
        if f5_finished:
            lines.append(f"  F5複勝: {f5_finished}頭 / 入着: {f5_hits}頭")
        if combo_finished:
            lines.append(f"  U2/S1: {combo_finished}レース / 三連複的中: {combo_hits}レース")
        lines.append("")

    # 総括コメント (Layer 1 のみ)
    if strict_races:
        lines.append("<b>━━━━━━━━━━━━━━</b>")
        if s_profit > 0:
            if s_hits == 1:
                lines.append("ほとんど 外し まちた。")
                lines.append("だが 1ターゲット で 全額 回収。")
            elif s_hits >= 2:
                lines.append("複数 撃破。良い 仕事 で だす。")
            else:
                lines.append("プラス で 終了。")
        elif s_profit < 0:
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

    msg = format_v6_results(data)
    ok = send_telegram(msg)
    logger.info(f"results v6 sent={ok}")
    return 0 if ok else 1


# Backward compatibility
def format_results(data: dict) -> str:
    return format_v6_results(data)


def format_v5_results(data: dict) -> str:
    return format_v6_results(data)


if __name__ == "__main__":
    sys.exit(main())
