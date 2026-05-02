#!/usr/bin/env python3
"""穴党参謀AI: 09:00 本日の本命配信.

Layer 1 (NAR 本命厳格): 火水木 + 旧強5会場 + 6-12頭 + 5-8人気 + 2-3エンジン一致 → 単勝
clean 2ヶ月実績 (n=145): 回収率 396.9% / Bootstrap CI 95%下限 225%
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


def format_silence(today: str, weekday: str) -> str:
    if weekday in ("土", "日"):
        return "\n".join([
            f"🌑 <b>{today} 穴党参謀AI</b>",
            "",
            "本日は配信ありません。",
            "",
            f"<b>{weekday}曜</b>は Layer 1（本命厳格）の対象外です。",
            "Layer 1 の配信は<b>火水木のみ</b>になります。",
        ])
    if weekday == "月":
        return "\n".join([
            f"🌑 <b>{today} 穴党参謀AI</b>",
            "",
            "本日は配信ありません。",
            "",
            "<b>月曜</b>は Layer 1 の対象外です。",
            "明日以降、火水木で本命配信を予定しています。",
        ])
    if weekday == "金":
        return "\n".join([
            f"🌑 <b>{today} 穴党参謀AI</b>",
            "",
            "本日は配信ありません。",
            "",
            "<b>金曜</b>は Layer 1 の対象外です。",
            "Layer 1 の配信は<b>火水木のみ</b>になります。",
        ])
    # 火水木 で該当無し
    return "\n".join([
        f"🌑 <b>{today} 穴党参謀AI</b>",
        "",
        "本日は該当なしのため配信ありません。",
        "",
        "条件: <b>火水木 + 旧強5会場 + 6-12頭 + 5-8人気 + 2-3エンジン一致</b>",
        "条件を厳格に絞っているため、該当しない日も少なくありません。",
    ])


def format_strict_section(strict_races: list) -> str:
    """Layer 1 (NAR本命厳格) 本命一覧."""
    lines = [
        "🔥 <b>Layer 1 — 本命厳格（旧強5会場）</b>",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "全本命 <b>単勝100円</b>",
        "<i>過去2ヶ月実績: 回収率 396.9% / CI下限 225%</i>",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "",
    ]
    s_sorted = sorted(strict_races, key=lambda r: r.get("start_time") or "99:99")
    for i, r in enumerate(s_sorted, 1):
        cons = r.get("consensus") or {}
        time_str = r.get("start_time") or "—"
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        hn = cons.get("horse_number", "?")
        name = cons.get("horse_name", "?")
        pop = r.get("popularity_rank")
        pop_str = f"{pop}番人気" if pop else "?番人気"
        cnt = cons.get("count", 0)
        lines.append(f"━ <b>本命{i}</b> ━")
        lines.append(f"📍 <b>{venue} {rn}R</b>  ⏰ {time_str}")
        lines.append(f"◎ <b>{hn}番 {name}</b>（{pop_str}）")
        lines.append(f"🎯 単勝 100円")
        lines.append(f"🤝 独自AI 4基中 <b>{cnt}基が一致</b>")
        lines.append("")

    return "\n".join(lines)


def format_obihiro_section(obihiro_races: list) -> str:
    """Layer 2 (帯広中穴) 一覧 — 複勝+ワイドBOX."""
    from itertools import combinations
    lines = [
        "🟣 <b>Layer 2 — 帯広中穴（ばんえい）</b>",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "<i>独自AI 4基 top3 union × 人気5-10位を 複勝+ワイドBOX</i>",
        "<i>過去2ヶ月実績: 複勝 131% / ワイドBOX 149%</i>",
        "",
    ]
    o_sorted = sorted(obihiro_races, key=lambda r: r.get("start_time") or "99:99")
    for r in o_sorted:
        time_str = r.get("start_time") or "—"
        rn = r.get("race_number", 0)
        horses = r.get("obihiro_horses") or []
        if not horses:
            continue
        nums = [str(h.get("horse_number")) for h in horses]
        lines.append(f"📍 <b>帯広 {rn}R</b>  ⏰ {time_str}")
        for h in horses:
            lines.append(
                f"  🐴 <b>{h.get('horse_number','?')}番 {h.get('horse_name','?')}</b> "
                f"（{h.get('popularity','?')}番人気）一致 {h.get('vote_count','?')}/4"
            )
        lines.append(f"  🎯 複勝: <b>各馬 100円</b>（{len(horses)}点）")
        if len(horses) >= 2:
            pair_disp = ", ".join(f"{a}-{b}" for a, b in combinations(nums, 2))
            n_pairs = len(list(combinations(nums, 2)))
            lines.append(f"  🎯 ワイドBOX: <b>{pair_disp}</b> 各100円（{n_pairs}点）")
        lines.append("")

    return "\n".join(lines)


def format_jra_section(jra_races: list) -> str:
    """Layer 3 (JRA S級) 一覧 — 複勝+馬連BOX3+三連複1点."""
    from itertools import combinations
    lines = [
        "🔵 <b>Layer 3 — JRA S級（週末）</b>",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "<i>独自AI 4基 top3 投票合議の3戦略同時運用</i>",
        "<i>過去2ヶ月実績: F5複勝 131% / U2馬連 326% / S1三連複 837%</i>",
        "",
    ]
    j_sorted = sorted(jra_races, key=lambda r: r.get("start_time") or "99:99")
    for r in j_sorted:
        time_str = r.get("start_time") or "—"
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        f5 = r.get("jra_f5_horses") or []
        top3 = r.get("jra_top3_horses") or []

        lines.append(f"📍 <b>{venue} {rn}R</b>  ⏰ {time_str}")
        # F5複勝
        if f5:
            for h in f5:
                lines.append(
                    f"  💎 <b>F5複勝</b>: <b>{h.get('horse_number','?')}番 {h.get('horse_name','?')}</b> "
                    f"（{h.get('popularity','?')}番人気）一致 {h.get('vote_count','?')}/4"
                )
        # U2/S1 共通 TOP3頭
        if len(top3) == 3:
            nums = [str(h.get("horse_number")) for h in top3]
            names = [h.get("horse_name", "?") for h in top3]
            disp = " / ".join(f"{n}.{nm[:8]}" for n, nm in zip(nums, names))
            lines.append(f"  🎯 <b>U2馬連BOX3</b>: " + ", ".join(f"{a}-{b}" for a, b in combinations(nums, 2)))
            lines.append(f"  🎯 <b>S1三連複1点</b>: {nums[0]}-{nums[1]}-{nums[2]}（{disp}）")
        lines.append("")

    return "\n".join(lines)


def format_v6(data: dict) -> str:
    races = data.get("races", []) or []
    weekday = data.get("weekday", "?")
    today = date_display(data.get("date", ""))

    strict_races = [r for r in races if r.get("is_golden_strict")]
    # Layer 2 (帯広) は 2026-04-27 無効化
    obihiro_races: list = []
    jra_races = [r for r in races
                 if r.get("is_layer3_jra_f5") or r.get("is_layer3_jra_combo")]

    if not strict_races and not obihiro_races and not jra_races:
        return format_silence(today, weekday)

    # === 投資金額の概算計算 ===
    l1_points = len(strict_races)
    l1_yen = l1_points * 100
    f5_points = sum(len(r.get("jra_f5_horses") or []) for r in jra_races)
    u2_points = sum(3 for r in jra_races if r.get("is_layer3_jra_combo"))
    s1_points = sum(1 for r in jra_races if r.get("is_layer3_jra_combo"))
    l3_full_points = f5_points + u2_points + s1_points
    l3_full_yen = l3_full_points * 100
    l3_mid_points = f5_points + s1_points
    l3_mid_yen = l3_mid_points * 100
    l3_low_points = s1_points
    l3_low_yen = l3_low_points * 100

    # === 発走時刻サマリ ===
    schedule_items: list = []
    for r in strict_races:
        schedule_items.append({
            "time": r.get("start_time") or "—",
            "venue": r.get("venue", ""),
            "race_no": r.get("race_number", 0),
            "label": "L1単勝",
            "icon": "🔥",
        })
    for r in jra_races:
        label_parts = []
        if r.get("is_layer3_jra_f5"): label_parts.append("F5")
        if r.get("is_layer3_jra_combo"): label_parts.append("U2/S1")
        schedule_items.append({
            "time": r.get("start_time") or "—",
            "venue": r.get("venue", ""),
            "race_no": r.get("race_number", 0),
            "label": "L3 " + "+".join(label_parts),
            "icon": "🔵",
        })

    def _time_sort_key(item):
        t = item.get("time") or "99:99"
        if t == "—": return "99:99"
        return t

    schedule_items.sort(key=_time_sort_key)

    lines = [f"☀️ <b>{today} 穴党参謀AI 本日の本命</b>", ""]

    # 発走スケジュール
    if schedule_items:
        lines.append("⏰ <b>本日の発走スケジュール</b>")
        lines.append("<b>━━━━━━━━━━━━━━━━━━</b>")
        for item in schedule_items:
            lines.append(f"  {item['icon']} <b>{item['time']}</b>  {item['venue']} {item['race_no']}R  <i>{item['label']}</i>")
        lines.append("")

    if strict_races:
        lines.append(format_strict_section(strict_races))
    if obihiro_races:
        if strict_races: lines.append("")
        lines.append(format_obihiro_section(obihiro_races))
    if jra_races:
        if strict_races or obihiro_races: lines.append("")
        lines.append(format_jra_section(jra_races))

    # === 推奨投資パターン ===
    if strict_races or jra_races:
        lines.append("<b>━━━━━━━━━━━━━━━━━━</b>")
        lines.append("💰 <b>本日の推奨投資パターン</b>")
        lines.append("")
        if strict_races and not jra_races:
            lines.append(f"📍 <b>Layer 1 のみ</b>: {l1_points}点 = <b>¥{l1_yen:,}</b>")
            lines.append("   （火水木 NAR本命厳格 単勝のみ、低リスク）")
        else:
            lines.append(f"🟢 <b>低リスク</b>（S1三連複1点のみ）: {l3_low_points}点 = <b>¥{l3_low_yen:,}</b>")
            lines.append("   ハイリターン狙い、的中率は低いが当たれば大きい")
            lines.append("")
            lines.append(f"🟡 <b>中</b>（F5複勝 + S1三連複1点）: {l3_mid_points}点 = <b>¥{l3_mid_yen:,}</b>")
            lines.append("   安定 + 一発、バランス型")
            lines.append("")
            lines.append(f"🔴 <b>フル</b>（Layer 1 + 全 Layer 3）: {l1_points + l3_full_points}点 = <b>¥{l1_yen + l3_full_yen:,}</b>")
            lines.append("   全戦略運用、利益も損失も最大化")
        lines.append("")
        lines.append("<i>※ 各自の予算に合わせて選択してください。</i>")
        lines.append("")

    lines.extend([
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "📊 <b>運用ルール</b>",
        "・各本命 <b>100円</b> 固定",
        "・人気薄狙いのため的中率は低めです",
        "・1点的中で投資額をカバーする運用",
        "",
        "📈 <b>過去2ヶ月実績（leakage除去後 clean）</b>",
        "・<b>Layer 1</b> NAR本命厳格 単勝: 396.9% / CI下限 225% / n=145",
        "・<b>Layer 3</b> JRA F5複勝: 131% / CI下限 118% / n=590",
        "・<b>Layer 3</b> JRA U2馬連BOX3: 326% / CI下限 213% / n=1116",
        "・<b>Layer 3</b> JRA S1三連複1点: 837% / CI下限 231% / n=372",
        "",
        "<i>毎日の結果は正直に公開しています。</i>",
    ])
    return "\n".join(lines)


def main():
    today = date_yyyymmdd_today()
    data = fetch_pattern(today)
    if not data:
        logger.error("no data")
        return 1

    msg = format_v6(data)
    if not msg:
        logger.info("no signals — silent")
        return 0

    ok = send_telegram_long(msg)
    logger.info(f"strict sent={ok}")
    return 0 if ok else 1


# 後方互換 (旧 timer 参照)
def format_strict(data: dict) -> str:
    return format_v6(data)


def format_v5(data: dict) -> str:
    return format_v6(data)


if __name__ == "__main__":
    sys.exit(main())
