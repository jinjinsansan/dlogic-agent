#!/usr/bin/env python3
"""競馬GANTZ: 09:00 任務指令 v6 — Layer 1 (NAR本命厳格).

条件: NAR + 火水木 + 旧強5会場 + 6-12頭 + 5-8人気 + 2-3エンジン一致 → 単勝
clean 2ヶ月実績 (n=145): 回収率 396.9% / Bootstrap CI 95%下限 225%
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


def format_silence(today: str, weekday: str) -> str:
    if weekday in ("土", "日"):
        return "\n".join([
            f"🌑 <b>{today}</b>",
            "",
            "玉 は 静か で だす。",
            "本日 任務 は あり ま せん。",
            "",
            f"<b>{weekday}曜</b> は 玉 が 動か ない 日 で だす。",
            "本物 の 仕事 は 火水木 のみ で だす。",
            "",
            "それ が 競馬GANTZ の 仕様 で だす。",
        ])
    if weekday == "月":
        return "\n".join([
            f"🌑 <b>{today}</b>",
            "",
            "玉 は 静か で だす。",
            "本日 任務 は あり ま せん。",
            "",
            "<b>月曜</b> は 玉 が 動か ない 日 で だす。",
            "本物 の 仕事 は 火水木 で 動き まち。",
            "",
            "明日 から 任務 始まる かも しれ まち。",
        ])
    if weekday == "金":
        return "\n".join([
            f"🌑 <b>{today}</b>",
            "",
            "玉 は 静か で だす。",
            "本日 任務 は あり ま せん。",
            "",
            "<b>金曜</b> は 玉 が 動か ない 日 で だす。",
            "本物 の 仕事 は 火水木 のみ で だす。",
        ])
    # 火水木 で該当無し
    return "\n".join([
        f"🌑 <b>{today}</b>",
        "",
        "玉 は 動か なかった で だす。",
        "本日 該当 ターゲット 無し で 沈黙 で だす。",
        "",
        "条件: <b>火水木 + 旧強5会場 + 6-12頭 + 5-8人気 + 2-3 一致</b>",
        "厳格 で だす。 該当 し ない 日 が 普通 で だす。",
    ])


def format_strict_section(strict_races: list) -> str:
    """Layer 1 (NAR本命厳格) ターゲット一覧."""
    lines = [
        "🔥🔥🔥 <b>Layer 1 — 本命厳格 (旧強5会場)</b> 🔥🔥🔥",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "🚨 全ターゲット <b>単勝100円</b>",
        "<i>過去2ヶ月: 回収率396.9% / CI下限225%</i>",
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
        pop_str = f"{pop}人気" if pop else "?"
        cnt = cons.get("count", 0)
        lines.append(f"━ <b>ターゲット{i}</b> ━")
        lines.append(f"📍 <b>{venue} {rn}R</b>  ⏰ <b>{time_str}</b>")
        lines.append(f"🐎 <b>{hn}番 {name}</b> ({pop_str})")
        lines.append(f"🎯 単勝 <b>{hn}</b>")
        lines.append(f"🤝 一致 <b>{cnt}/4</b> エンジン")
        lines.append("")

    return "\n".join(lines)


def format_obihiro_section(obihiro_races: list) -> str:
    """Layer 2 (帯広中穴) ターゲット一覧 — 複勝+ワイドBOX."""
    from itertools import combinations
    lines = [
        "🟣 <b>Layer 2 — 帯広中穴 (ばんえい)</b>",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "<i>4エンジン top3 union × 人気5-10位 を 複勝+ワイドBOX</i>",
        "<i>過去2ヶ月: 複勝131% / ワイドBOX149%</i>",
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
        nums_disp = "/".join(nums)
        lines.append(f"📍 <b>帯広 {rn}R</b>  ⏰ <b>{time_str}</b>")
        for h in horses:
            lines.append(
                f"  🐴 <b>{h.get('horse_number','?')}番 {h.get('horse_name','?')}</b> "
                f"({h.get('popularity','?')}人気) 一致{h.get('vote_count','?')}/4"
            )
        lines.append(f"  🎯 複勝: <b>各馬 100円</b> ({len(horses)}点)")
        if len(horses) >= 2:
            pair_disp = ", ".join(f"{a}-{b}" for a, b in combinations(nums, 2))
            n_pairs = len(list(combinations(nums, 2)))
            lines.append(f"  🎯 ワイドBOX: <b>{pair_disp}</b> 各100円 ({n_pairs}点)")
        lines.append("")

    return "\n".join(lines)


def format_jra_section(jra_races: list) -> str:
    """Layer 3 (JRA S級) ターゲット一覧 — 複勝+馬連BOX3+三連複1点."""
    from itertools import combinations
    lines = [
        "🔵 <b>Layer 3 — JRA S級 (週末)</b>",
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "<i>4エンジン top3 投票合議の3戦略同時運用</i>",
        "<i>過去2ヶ月: F5複勝131% / U2馬連326% / S1三連複837%</i>",
        "",
    ]
    j_sorted = sorted(jra_races, key=lambda r: r.get("start_time") or "99:99")
    for r in j_sorted:
        time_str = r.get("start_time") or "—"
        venue = r.get("venue", "")
        rn = r.get("race_number", 0)
        f5 = r.get("jra_f5_horses") or []
        top3 = r.get("jra_top3_horses") or []

        lines.append(f"📍 <b>{venue} {rn}R</b>  ⏰ <b>{time_str}</b>")
        # F5複勝
        if f5:
            for h in f5:
                lines.append(
                    f"  💎 <b>F5複勝</b>: <b>{h.get('horse_number','?')}番 {h.get('horse_name','?')}</b> "
                    f"({h.get('popularity','?')}人気) 一致{h.get('vote_count','?')}/4"
                )
        # U2/S1 共通 TOP3頭
        if len(top3) == 3:
            nums = [str(h.get("horse_number")) for h in top3]
            names = [h.get("horse_name", "?") for h in top3]
            disp = " / ".join(f"{n}.{nm[:8]}" for n, nm in zip(nums, names))
            lines.append(f"  🎯 <b>U2馬連BOX3</b>: " + ", ".join(f"{a}-{b}" for a, b in combinations(nums, 2)))
            lines.append(f"  🎯 <b>S1三連複1点</b>: {nums[0]}-{nums[1]}-{nums[2]} ({disp})")
        lines.append("")

    return "\n".join(lines)


def format_v6(data: dict) -> str:
    from itertools import combinations
    races = data.get("races", []) or []
    weekday = data.get("weekday", "?")
    today = date_display(data.get("date", ""))

    strict_races = [r for r in races if r.get("is_golden_strict")]
    # Layer 2 (帯広) は 2026-04-27 無効化 — ばんえい未学習エンジンの偶然数字とみなし配信除外
    obihiro_races: list = []  # [r for r in races if r.get("is_layer2_obihiro")]
    jra_races = [r for r in races
                 if r.get("is_layer3_jra_f5") or r.get("is_layer3_jra_combo")]

    if not strict_races and not obihiro_races and not jra_races:
        return format_silence(today, weekday)

    # === 投資金額の概算計算 ===
    # Layer 1: 単勝1点/件
    l1_points = len(strict_races)
    l1_yen = l1_points * 100
    # Layer 3: F5複勝(1馬1点) + U2馬連BOX3(3点) + S1三連複1点(1点)
    f5_points = sum(len(r.get("jra_f5_horses") or []) for r in jra_races)
    u2_points = sum(3 for r in jra_races if r.get("is_layer3_jra_combo"))
    s1_points = sum(1 for r in jra_races if r.get("is_layer3_jra_combo"))
    l3_full_points = f5_points + u2_points + s1_points
    l3_full_yen = l3_full_points * 100
    l3_mid_points = f5_points + s1_points  # F5+S1 (馬連除外)
    l3_mid_yen = l3_mid_points * 100
    l3_low_points = s1_points  # S1のみ
    l3_low_yen = l3_low_points * 100

    lines = [f"☀️ <b>{today} 任務開始</b>", ""]
    if strict_races:
        lines.append(format_strict_section(strict_races))
    if obihiro_races:
        if strict_races: lines.append("")
        lines.append(format_obihiro_section(obihiro_races))
    if jra_races:
        if strict_races or obihiro_races: lines.append("")
        lines.append(format_jra_section(jra_races))

    # === 推奨投資パターン (Layer 1/3 ある場合のみ) ===
    if strict_races or jra_races:
        lines.append("<b>━━━━━━━━━━━━━━━━━━</b>")
        lines.append("💰 <b>本日 の 推奨 投資 パターン</b>")
        lines.append("")
        if strict_races and not jra_races:
            # Layer 1 のみ (火水木)
            lines.append(f"📍 <b>Layer 1 のみ</b>: {l1_points}点 = <b>¥{l1_yen:,}</b>")
            lines.append("   (火水木 NAR本命厳格 単勝のみ、低リスク)")
        else:
            # Layer 3 ある日 (土日)
            lines.append(f"🟢 <b>低リスク</b> (S1三連複1点のみ): {l3_low_points}点 = <b>¥{l3_low_yen:,}</b>")
            lines.append("   ハイリターン狙い、ほとんど外れるが当たれば大きい")
            lines.append("")
            lines.append(f"🟡 <b>中</b> (F5複勝 + S1三連複1点): {l3_mid_points}点 = <b>¥{l3_mid_yen:,}</b>")
            lines.append("   安定 + 一発、バランス型")
            lines.append("")
            lines.append(f"🔴 <b>フル</b> (Layer 1 + 全 Layer 3): {l1_points + l3_full_points}点 = <b>¥{l1_yen + l3_full_yen:,}</b>")
            lines.append("   GANTZ 全戦略、利益も損失も最大化")
        lines.append("")
        lines.append("<i>※ 自分の 予算 と 心臓 に 合う パターン を 選んで くだちい</i>")
        lines.append("")

    lines.extend([
        "<b>━━━━━━━━━━━━━━━━━━</b>",
        "💎 <b>運用ルール</b>",
        "・各ターゲット <b>100円</b> (固定)",
        "・絞らない、外しても続ける",
        "・ほとんど 失敗 し まち",
        '・"1点で 全額 回収" が 仕様 で だす',
        "",
        "📊 <b>過去2ヶ月 実績 (clean, leakage除去)</b>",
        "・<b>Layer 1</b> NAR本命厳格 単勝: 396.9% / CI下限225% / n=145",
        "・<b>Layer 3</b> JRA F5複勝: 131% / CI下限118% / n=590",
        "・<b>Layer 3</b> JRA U2馬連BOX3: 326% / CI下限213% / n=1116",
        "・<b>Layer 3</b> JRA S1三連複1点: 837% / CI下限231% / n=372",
        "",
        "<i>毎日 結果 を 正直 に 公開 し まち</i>",
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

    ok = send_telegram(msg)
    logger.info(f"v6 sent={ok}")
    return 0 if ok else 1


# Backwards compatibility (old timer references)
def format_strict(data: dict) -> str:
    return format_v6(data)


def format_v5(data: dict) -> str:
    return format_v6(data)


if __name__ == "__main__":
    sys.exit(main())
