#!/usr/bin/env python3
"""競馬GANTZ: 09:00 任務指令 v5 — 3層運用 (ピンポイント特異点 / 信頼度・最高 / 信頼度・高)."""
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


def format_silence(today: str, weekday: str) -> str:
    return "\n".join([
        f"🌑 <b>{today}</b>",
        "",
        "玉 は 静か で だす。",
        "本日 任務 は あり ま せん。",
        "",
        f"<b>{weekday}曜</b> は 玉 が 動か ない 日 で だす。",
        "仕事 は 月曜 から 再開 し まち。",
        "",
        "ほとんど の 日 は 仕事 が 来ない。",
        "来た 日 は 必ず 仕事 を 受けて くだちい。",
        "",
        "それ が 競馬GANTZ の 仕様 で だす。",
    ])


def format_pinpoint_section(pinpoint_races: list) -> str:
    """ピンポイント特異点セクション (該当レースのみ、3軸で recov>=200%)."""
    if not pinpoint_races:
        return ""
    lines = [
        "🌟🌟🌟 <b>ピンポイント特異点 出現</b> 🌟🌟🌟",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "<b>過去1年で200%超の超特殊条件、本日該当!</b>",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "",
    ]
    pp_sorted = sorted(pinpoint_races, key=lambda r: r.get("start_time") or "99:99")
    for r in pp_sorted:
        cons = r.get("consensus") or {}
        pp = r.get("pinpoint") or {}
        time_str = r.get("start_time") or "—"
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        hn = cons.get("horse_number", "?")
        name = cons.get("horse_name", "?")

        lines.append(f"📍 <b>{venue} {rn}R</b>  ⏰ <b>{time_str}</b>")
        lines.append(f"🐎 <b>{hn}番 {name}</b>")
        lines.append(f"🎯 武器: <b>単勝 {hn}</b>")
        lines.append(f"⚡ <b>{pp.get('venue')} × {pp.get('pop')}人気 × {pp.get('cons')}/4一致</b>")
        lines.append(f"   過去 {pp.get('n')}R 回収率 <b>{pp.get('recov')}%</b>")
        lines.append("")

    return "\n".join(lines)


def format_strict_section(strict_races: list, exclude_ids: set) -> str:
    """信頼度・最高 (A3) セクション. ピンポイントとの重複は除外."""
    races = [r for r in strict_races if r.get("race_id") not in exclude_ids]
    if not races:
        return ""
    lines = [
        "🔥🔥🔥 <b>信頼度・最高 任務</b> 🔥🔥🔥",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "🚨 全ターゲット <b>単勝100円</b> で買って くだちい",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "",
    ]
    s_sorted = sorted(races, key=lambda r: r.get("start_time") or "99:99")
    for i, r in enumerate(s_sorted, 1):
        cons = r.get("consensus") or {}
        time_str = r.get("start_time") or "—"
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        hn = cons.get("horse_number", "?")
        name = cons.get("horse_name", "?")
        lines.append(f"━ <b>ターゲット{i}</b> ━")
        lines.append(f"📍 <b>{venue} {rn}R</b>  ⏰ <b>{time_str}</b>")
        lines.append(f"🐎 <b>{hn}番 {name}</b>")
        lines.append(f"🎯 単勝 <b>{hn}</b>")
        lines.append("")

    return "\n".join(lines)


def format_high_section(high_races: list, exclude_ids: set) -> str:
    """信頼度・高 (A5) セクション. ピンポイント・最高との重複は除外し、コンパクト表示."""
    races = [r for r in high_races if r.get("race_id") not in exclude_ids]
    if not races:
        return ""
    lines = [
        "✅ <b>信頼度・高 (参考、人気不問)</b>",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "<i>南関東 (川崎/船橋/大井/浦和) で 2-3エンジン一致レース</i>",
        "<i>1年実績 回収率 約141%</i>",
        "",
    ]
    h_sorted = sorted(races, key=lambda r: r.get("start_time") or "99:99")
    for r in h_sorted:
        cons = r.get("consensus") or {}
        pop = r.get("popularity_rank")
        pop_str = f"{pop}人気" if pop else "?"
        time_str = r.get("start_time") or "—"
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        hn = cons.get("horse_number", "?")
        name = cons.get("horse_name", "?")
        lines.append(f"📍 {venue} {rn}R ⏰{time_str}  ◎{hn}.{name} ({pop_str})")

    return "\n".join(lines)


def format_v5(data: dict) -> str:
    races = data.get("races", []) or []
    weekday = data.get("weekday", "?")
    today = date_display(data.get("date", ""))

    pinpoint_races = [r for r in races if r.get("pinpoint")]
    strict_races = [r for r in races if r.get("is_golden_strict")]
    high_races = [r for r in races if r.get("is_golden_high")]

    if not pinpoint_races and not strict_races and not high_races:
        # 土日 or 該当ナシ → 沈黙投稿
        if weekday in ("土", "日"):
            return format_silence(today, weekday)
        return ""

    lines = [
        f"☀️ <b>{today} 任務開始</b>",
        "",
    ]

    pinpoint_ids = {r.get("race_id") for r in pinpoint_races}
    strict_ids = {r.get("race_id") for r in strict_races}

    # 1. Pinpoint
    pp_section = format_pinpoint_section(pinpoint_races)
    if pp_section:
        lines.append(pp_section)

    # 2. Strict (excluding pinpoint)
    s_section = format_strict_section(strict_races, exclude_ids=pinpoint_ids)
    if s_section:
        if pp_section: lines.append("")
        lines.append(s_section)

    # 3. High (excluding pinpoint and strict)
    excluded = pinpoint_ids | strict_ids
    h_section = format_high_section(high_races, exclude_ids=excluded)
    if h_section:
        if pp_section or s_section: lines.append("")
        lines.append(h_section)

    # Footer
    lines.append("")
    lines.append("<b>━━━━━━━━━━━━━━━━━━</b>")
    lines.append("💎 <b>運用ルール</b>")
    lines.append("・🌟 ピンポイント = <b>最優先</b>、必ず買う")
    lines.append("・🚀 信頼度・最高 = 全部 100円ずつ単勝")
    lines.append("・✅ 信頼度・高 = 参考、買えるだけ")
    lines.append("・絞らない、外しても続ける")
    lines.append("")
    lines.append("🔥 <b>仕様</b>")
    lines.append("ほとんど 失敗 し まち。")
    lines.append("だが <b>1〜2 撃破 で 全体 プラス</b>。")
    lines.append('"1点で 全額 回収" が 競馬GANTZ で だす。')
    lines.append("")
    lines.append("📊 <b>1年実績 (NAR 13,529レース)</b>")
    lines.append("🚀 信頼度・最高 (255R): 回収率 <b>320.6%</b> / 利益 +¥56,250")
    lines.append("✅ 信頼度・高 (2,591R): 回収率 <b>141.1%</b> / 利益 +¥106,470")
    lines.append("🌟 ピンポイント: 回収率 <b>200-505%</b>")

    return "\n".join(lines)


def main():
    today = date_yyyymmdd_today()
    data = fetch_pattern(today)
    if not data:
        logger.error("no data")
        return 1

    msg = format_v5(data)
    if not msg:
        logger.info("no signals — silent")
        return 0

    ok = send_telegram(msg)
    logger.info(f"v5 sent={ok}")
    return 0 if ok else 1


# Backwards compatibility
def format_strict(data: dict) -> str:
    """旧 format_strict の互換シム (v5 を呼ぶ)."""
    return format_v5(data)


if __name__ == "__main__":
    sys.exit(main())
