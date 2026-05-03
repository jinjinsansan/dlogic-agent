#!/usr/bin/env python3
"""穴党参謀AI: 23:00 戦果報告 — Layer 1〜3 統合.

100円単位で正直に当落報告。当たっても外れても全レース結果を公開。
"""
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


def _race_outcome_line(r: dict) -> list:
    cons = r.get("consensus") or {}
    venue = r.get("venue", "")
    rn = r.get("race_number", 0)
    cons_horse = cons.get("horse_number", "?")
    cons_name = cons.get("horse_name", "?")
    pop = r.get("popularity_rank")
    pop_str = f"{pop}番人気" if pop else "?番人気"
    result = r.get("result")

    head = f"📍 <b>{venue} {rn}R</b> ◎{cons_horse}.{cons_name}（{pop_str}）"
    if not result:
        return [head, "   → ⏳ 結果未確定"]

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
        return [head, f"   → 1着: <b>{winner}番 {winner_name}</b>  単勝 <b>¥{payout:,}</b>  🎯 <b>的中</b>"]
    return [head, f"   → 1着: {winner}番 {winner_name}  ✗ 外れ"]


def format_silence_results(today: str) -> str:
    return "\n".join([
        f"🌙 <b>{today} 戦果報告</b>",
        "",
        "本日は配信ありませんでした。",
        "",
        "条件を厳格に絞っているため、該当しない日も少なくありません。",
    ])


def _obihiro_result_lines(races: list) -> list:
    """Layer 2 (帯広中穴) の結果行を生成."""
    lines = []
    for r in sorted(races, key=lambda x: (x.get("start_time") or "99")):
        rn = r.get("race_number", 0)
        result = r.get("result") or {}
        obihiro_outcomes = result.get("obihiro_outcomes") or []

        lines.append(f"📍 <b>帯広 {rn}R</b>")
        if not result:
            lines.append("   → ⏳ 結果未確定")
            continue
        for oc in obihiro_outcomes:
            hn = oc.get("horse_number", "?")
            placed = oc.get("placed", False)
            fp = oc.get("fukusho_payout") or 0
            if placed:
                payout_str = f" 複勝 ¥{fp:,}" if fp else " 複勝 ✓（払戻額不明）"
                lines.append(f"   🐴 <b>{hn}番</b> → 3着内入着{payout_str} ✅")
            else:
                lines.append(f"   🐴 <b>{hn}番</b> → 着外 ✗")
    return lines


def _jra_result_lines(races: list) -> list:
    """Layer 3 (JRA S級) の結果行を生成."""
    lines = []
    for r in sorted(races, key=lambda x: (x.get("start_time") or "99")):
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        result = r.get("result") or {}
        f5_outcomes = result.get("f5_outcomes") or []
        l3_combo_hit = result.get("l3_combo_hit", False)
        l3_combo_payout = result.get("l3_combo_payout") or 0
        top3_list = result.get("top3") or []

        lines.append(f"📍 <b>{venue} {rn}R</b>")
        if not result:
            lines.append("   → ⏳ 結果未確定")
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
            payout_str = f" 三連複 ¥{l3_combo_payout:,}" if l3_combo_payout else " 三連複 ✓"
            lines.append(f"   🎯 U2/S1 {combo_str}{payout_str} 的中 ✅")
        else:
            actual = "-".join(str(t.get("horse_number", "?")) for t in top3_list[:3]) if top3_list else "?"
            lines.append(f"   🎯 U2/S1 → 外れ（実際の1-3着: {actual}）")
    return lines


def _jra_payout_summary(jra_races: list) -> list:
    """Layer 3 の 100円均等買い収支サマリーを生成."""
    f5_count = 0
    f5_hits = 0
    f5_payout = 0
    combo_count = 0
    combo_hits = 0
    combo_payout = 0

    for r in jra_races:
        result = r.get("result") or {}
        if not result:
            continue
        for oc in (result.get("f5_outcomes") or []):
            f5_count += 1
            if oc.get("placed"):
                f5_hits += 1
                f5_payout += oc.get("fukusho_payout") or 0
        # 三連複は1レース1点想定（U2/S1 → 三連複1点）
        # is_layer3_jra_combo フラグ持ちのレースだけカウント
        if r.get("is_layer3_jra_combo"):
            combo_count += 1
            if result.get("l3_combo_hit"):
                combo_hits += 1
                combo_payout += result.get("l3_combo_payout") or 0

    if f5_count == 0 and combo_count == 0:
        return []

    # 払戻データがまだ取れていない（pipeline 未整備）の場合は誤解を招くサマリーを出さない
    # 的中があるはずなのに payout が全部0 → データソース未配線。表示スキップ。
    has_hits = f5_hits > 0 or combo_hits > 0
    has_payout = f5_payout > 0 or combo_payout > 0
    if has_hits and not has_payout:
        return ["", "<i>(払戻金額データはまだ取得経路を整備中)</i>"]

    f5_invest = f5_count * 100
    f5_profit = f5_payout - f5_invest
    f5_recovery = round(f5_payout / f5_invest * 100) if f5_invest > 0 else 0
    f5_sign = "+" if f5_profit >= 0 else ""

    combo_invest = combo_count * 100
    combo_profit = combo_payout - combo_invest
    combo_recovery = round(combo_payout / combo_invest * 100) if combo_invest > 0 else 0
    combo_sign = "+" if combo_profit >= 0 else ""

    total_invest = f5_invest + combo_invest
    total_payout = f5_payout + combo_payout
    total_profit = total_payout - total_invest
    total_recovery = round(total_payout / total_invest * 100) if total_invest > 0 else 0
    total_sign = "+" if total_profit >= 0 else ""
    total_emoji = "✨" if total_profit > 0 else ("💧" if total_profit < 0 else "")

    lines = ["", "📊 <b>100円均等買い 戦果サマリー</b>"]
    if f5_count:
        lines.append(
            f"  💎 F5 複勝: {f5_count}点 投資¥{f5_invest:,} → 払戻¥{f5_payout:,} "
            f"→ 収支<b>¥{f5_sign}{f5_profit:,}</b>（回収率 {f5_recovery}%）"
        )
    if combo_count:
        lines.append(
            f"  🎯 U2/S1 三連複: {combo_count}点 投資¥{combo_invest:,} → 払戻¥{combo_payout:,} "
            f"→ 収支<b>¥{combo_sign}{combo_profit:,}</b>（回収率 {combo_recovery}%）"
        )
    if f5_count and combo_count:
        lines.append(
            f"  💰 <b>合計</b>: 投資¥{total_invest:,} → 払戻¥{total_payout:,} "
            f"→ 収支<b>¥{total_sign}{total_profit:,}</b>（回収率 {total_recovery}%）{total_emoji}"
        )
    return lines


def format_v6_results(data: dict) -> str:
    races = data.get("races", []) or []
    strict_races = [r for r in races if r.get("is_golden_strict")]
    obihiro_races: list = []  # Layer 2 (帯広) 無効化中
    jra_races = [r for r in races if r.get("is_layer3_jra_f5") or r.get("is_layer3_jra_combo")]

    today = date_display(data.get("date", ""))

    if not strict_races and not obihiro_races and not jra_races:
        return format_silence_results(today)

    summary = data.get("summary") or {}
    s_finished = summary.get("strict_finished", 0)
    s_hits = summary.get("strict_hits", 0)
    s_profit = summary.get("strict_profit", 0)

    lines = [
        f"🌙 <b>{today} 穴党参謀AI 戦果報告</b>",
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
        recovery_pct = round(payout / invest * 100) if invest > 0 else 0
        lines.append(f"  本命: {s_finished}件 / 的中: {s_hits}件")
        lines.append(f"  収支: <b>¥{sign}{s_profit:,}</b>（投資¥{invest:,} → 払戻¥{payout:,}、回収率 {recovery_pct}%）{emoji}")
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

    # Layer 3 (JRA S級) — 2026-05-03 配信停止（仁さん判断）
    # 過去成績不振のため JRA 配信廃止。コードは残置、必要なら再有効化可能。
    # 元のロジックは backup ファイル参照。

    # 総括コメント (Layer 1 のみ)
    if strict_races:
        lines.append("<b>━━━━━━━━━━━━━━</b>")
        if s_profit > 0:
            if s_hits == 1:
                lines.append("ほとんどが外れでしたが、1点的中で投資額をカバーできました。")
            elif s_hits >= 2:
                lines.append("複数的中。良い結果です。")
            else:
                lines.append("プラスで終了しました。")
        elif s_profit < 0:
            lines.append("本日はマイナスで終了しました。")
            lines.append("人気薄狙いのため的中率は低く、淡々と続けることが運用前提です。")
        else:
            lines.append("収支は±0で終了しました。")

    return "\n".join(lines)


def main():
    today = date_yyyymmdd_today()
    data = fetch_pattern(today)
    if not data:
        logger.error("no data")
        return 1

    msg = format_v6_results(data)
    ok = send_telegram_long(msg)
    logger.info(f"results sent={ok}")
    return 0 if ok else 1


# Backward compatibility
def format_results(data: dict) -> str:
    return format_v6_results(data)


def format_v5_results(data: dict) -> str:
    return format_v6_results(data)


if __name__ == "__main__":
    sys.exit(main())
