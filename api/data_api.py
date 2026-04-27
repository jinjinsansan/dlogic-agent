"""
Data API — レースデータを外部プロジェクト（dlogic-note等）に提供するREST API
既存のスクレイパー/プリフェッチ/アーカイブをHTTPエンドポイントとして公開する
"""
import json
import logging
import os
from collections import Counter
from datetime import datetime
from flask import Blueprint, request, jsonify

SNAPSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'golden_history'
)

from tools.executor import (
    _get_today_races, _get_race_entries, _resolve_netkeiba_race_id,
    _get_predictions, _load_prefetch,
)
from scrapers.odds import fetch_realtime_odds
from db.supabase_client import get_client

logger = logging.getLogger(__name__)

bp = Blueprint("data_api", __name__, url_prefix="/api/data")

# Golden pattern v6 (2026-04-27 Plan A デプロイ)
# Clean 2ヶ月データで leakage 除去後、4/25旧監査の本命厳格条件のみが S級として残った
# (CI下限 225%, n=145, 回収率396.9%)。v5 は汚染データ由来として全廃止。
#
# Layer 1 (NAR strict): NAR + 火水木 + 6-12頭 + 5-8人気 + 旧強5会場 + 2-3一致
#   → is_golden_strict (単勝¥100)
# Layer 2 (帯広中穴): 帯広 + 4エンジン top3 union の人気5-10位馬 (複勝+ワイドBOX)
#   → is_layer2_obihiro / obihiro_horses
# Layer 3 (JRA S級): JRA 土日 + F5複勝 / U2馬連BOX3 / S1三連複1点
#   → is_layer3_jra_f5 / is_layer3_jra_combo

# Layer 1 (NAR本命厳格)
OLD_STRONG5 = {"園田", "水沢", "高知", "笠松", "金沢"}
LAYER1_WEEKDAYS = {1, 2, 3}  # 火(1), 水(2), 木(3)
LAYER1_FIELD_MIN = 6
LAYER1_FIELD_MAX = 12
LAYER1_POP_MIN = 5
LAYER1_POP_MAX = 8

# Layer 2 (帯広中穴) — 2026-04-27 無効化
# 理由: Dlogic 等のエンジンは ばんえい を学習データに含んでおらず、
# clean 2ヶ月の数字 (複勝131%, ワイドBOX149%) は偶然の可能性大。
# 平地競馬と物理的に異なる (馬力・斤量・脚質) ため、
# 平地データ主体の現エンジンが ばんえい で機能する根拠が薄い。
# データ蓄積後 (6ヶ月+) に再評価予定。
LAYER2_ENABLED = False  # ← 再有効化はここを True に
LAYER2_VENUES = {"帯広"}
LAYER2_POP_MIN = 5
LAYER2_POP_MAX = 10
LAYER2_MAX_HORSES = 4

# Layer 3 (JRA S級): 週末 JRA 用。S級14戦略から 安定3戦略を選抜
# - F5_3engT3合議の複勝 (n=590, 130.6%, CI下限118%) ← 安定運用
# - U2_TOP3投票の馬連BOX3 (n=1116, 325.9%, CI下限213%) ← バランス
# - S1_TOP3投票の三連複1点 (n=372, 836.9%, CI下限231%) ← ハイリターン
LAYER3_MIN_T3_CONS = 3   # F5: 3エンジン以上 top3 一致
LAYER3_T3_TOP_N = 3      # U2/S1: 投票上位3頭から馬連/三連複組合せ
LAYER3_WEEKDAYS = {5, 6}  # 土(5), 日(6) のみ — 週末JRA限定

GOLDEN_ENGINE_KEYS = ["Dlogic", "Ilogic", "ViewLogic", "MetaLogic"]

# 旧定数 (互換用、新ロジックでは未使用)
GOLDEN_STRONG_VENUES_V4 = {"川崎", "船橋", "大井", "浦和", "門別", "笠松"}
GOLDEN_SOUTH_NANKAN = {"川崎", "船橋", "大井", "浦和"}
GOLDEN_BEST_VENUES = OLD_STRONG5
GOLDEN_BEST_WEEKDAYS = LAYER1_WEEKDAYS
GOLDEN_PER_WEEKDAY = {0: None, 1: None, 2: None, 3: None, 4: None, 5: None, 6: None}
PINPOINT_PATTERNS = []  # v5 ピンポイントは汚染データ由来、廃止


@bp.route("/races", methods=["GET"])
def get_races():
    """
    レース一覧を取得

    Query params:
        date: YYYYMMDD (default: today)
        type: jra or nar (default: jra)
        venue: 競馬場名フィルタ (optional)

    Returns:
        { races: [...], count: int }
    """
    params = {
        "date": request.args.get("date", ""),
        "race_type": request.args.get("type", "jra"),
        "venue": request.args.get("venue", ""),
    }
    # Remove empty strings so executor uses defaults
    params = {k: v for k, v in params.items() if v}
    if "race_type" not in params:
        params["race_type"] = "jra"

    try:
        result_json = _get_today_races(params)
        return jsonify(json.loads(result_json))
    except Exception as e:
        logger.error(f"Data API /races error: {e}")
        return jsonify({"error": str(e), "races": [], "count": 0}), 500


@bp.route("/entries/<race_id>", methods=["GET"])
def get_entries(race_id: str):
    """
    出馬表を取得

    Path params:
        race_id: netkeiba race ID

    Query params:
        type: jra or nar (default: jra)

    Returns:
        { race_id, race_name, venue, distance, entries: [...], ... }
    """
    params = {
        "race_id": race_id,
        "race_type": request.args.get("type", "jra"),
    }

    try:
        result_json = _get_race_entries(params)
        return jsonify(json.loads(result_json))
    except Exception as e:
        logger.error(f"Data API /entries error: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/odds/<race_id>", methods=["GET"])
def get_odds(race_id: str):
    """
    リアルタイムオッズを取得（Lightpanda経由）

    Path params:
        race_id: custom or netkeiba race ID

    Query params:
        type: jra or nar (default: jra)

    Returns:
        { race_id, odds: {horse_number: odds_value, ...} }
    """
    race_type = request.args.get("type", "jra")

    try:
        netkeiba_id = _resolve_netkeiba_race_id(race_id, race_type)
        odds = fetch_realtime_odds(netkeiba_id, race_type)
        return jsonify({"race_id": race_id, "odds": odds or {}})
    except Exception as e:
        logger.error(f"Data API /odds error: {e}")
        return jsonify({"error": str(e), "odds": {}}), 500


def _fetch_results_for_date(date_str: str) -> dict:
    """Fetch all finished race results for a given date. Returns {race_id: result_dict}."""
    if len(date_str) != 8:
        return {}
    date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    try:
        sb = get_client()
        res = sb.table("race_results").select(
            "race_id,winner_number,win_payout,result_json,status"
        ).eq("race_date", date_iso).execute()
        out = {}
        for r in (res.data or []):
            if r.get("status") != "finished":
                continue
            rj = r.get("result_json")
            if isinstance(rj, str):
                try:
                    rj = json.loads(rj)
                except Exception:
                    rj = None
            r["result_json"] = rj
            out[r["race_id"]] = r
        return out
    except Exception as e:
        logger.warning(f"_fetch_results_for_date failed: {e}")
        return {}


def _build_race_result(eval_result: dict, race_result: dict | None) -> dict | None:
    """Attach race outcome and per-layer P/L info."""
    if not race_result:
        return None
    rj = race_result.get("result_json") or {}
    top3 = rj.get("top3") or []
    payouts = rj.get("payouts") or {}
    cons_horse = eval_result.get("consensus", {}).get("horse_number")
    winner_number = race_result.get("winner_number")
    win_payout = race_result.get("win_payout") or 0

    top3_numbers = [t.get("horse_number") for t in top3 if t.get("horse_number") is not None]
    did_win = bool(cons_horse and cons_horse == winner_number)
    did_place = bool(cons_horse and cons_horse in top3_numbers)

    # Layer 1 profit (単勝)
    is_buy = eval_result.get("is_golden_loose") or eval_result.get("is_golden_strict")
    profit = None
    if is_buy:
        profit = (win_payout - 100) if did_win else -100

    # Layer 2 (帯広中穴) outcome per-horse: check placement in top3
    obihiro_outcomes = []
    for h in (eval_result.get("obihiro_horses") or []):
        hn = h.get("horse_number")
        placed = hn in top3_numbers
        fukusho_payout = 0
        for entry in (payouts.get("fukusho") or []):
            if entry.get("horse_number") == hn:
                fukusho_payout = entry.get("payout") or 0
                break
        obihiro_outcomes.append({
            "horse_number": hn,
            "placed": placed,
            "fukusho_payout": fukusho_payout,
        })

    # Layer 3 F5 (複勝) outcome per-horse
    f5_outcomes = []
    for h in (eval_result.get("jra_f5_horses") or []):
        hn = h.get("horse_number")
        placed = hn in top3_numbers
        fukusho_payout = 0
        for entry in (payouts.get("fukusho") or []):
            if entry.get("horse_number") == hn:
                fukusho_payout = entry.get("payout") or 0
                break
        f5_outcomes.append({"horse_number": hn, "placed": placed, "fukusho_payout": fukusho_payout})

    # Layer 3 U2/S1 outcome
    top3_pick = [h.get("horse_number") for h in (eval_result.get("jra_top3_horses") or [])]
    top3_pick_set = set(top3_pick)
    top3_result_set = set(top3_numbers[:3])
    l3_combo_hit = len(top3_pick) == 3 and top3_pick_set == top3_result_set

    return {
        "status": "finished",
        "winner_number": winner_number,
        "win_payout": win_payout,
        "top3": top3,
        "did_consensus_win": did_win,
        "did_consensus_place": did_place,
        "profit_yen": profit,
        "obihiro_outcomes": obihiro_outcomes,
        "f5_outcomes": f5_outcomes,
        "l3_combo_hit": l3_combo_hit,
    }


def _evaluate_golden_pattern(race: dict, weekday: int) -> dict:
    """Compute consensus, popularity, and golden flags for a single race."""
    horse_numbers = race.get("horse_numbers") or []
    horses = race.get("horses") or []
    odds_arr = race.get("odds") or []
    horse_map = {n: (horses[i] if i < len(horses) else "") for i, n in enumerate(horse_numbers)}

    # Popularity rank from odds (lower odds = more favored)
    pop_rank_map = {}
    if odds_arr and len(odds_arr) == len(horse_numbers):
        valid_pairs = [(n, o) for n, o in zip(horse_numbers, odds_arr) if o is not None and o > 0]
        sorted_pairs = sorted(valid_pairs, key=lambda x: x[1])
        pop_rank_map = {hn: i + 1 for i, (hn, _) in enumerate(sorted_pairs)}

    # Get engine predictions
    pred_params = {
        "race_id": race.get("race_id", ""),
        "horses": horses,
        "horse_numbers": horse_numbers,
        "venue": race.get("venue", ""),
        "race_number": race.get("race_number", 0),
        "jockeys": race.get("jockeys", []),
        "posts": race.get("posts", []),
        "distance": race.get("distance", ""),
        "track_condition": race.get("track_condition", "良"),
    }
    engine_picks = {}      # top1 picks (Layer 1 用)
    engine_top3 = {}       # top3 picks (Layer 2 用)
    try:
        preds_json = _get_predictions(pred_params)
        preds_data = json.loads(preds_json)
        preds = preds_data.get("predictions", {})
        for label in GOLDEN_ENGINE_KEYS:
            arr = preds.get(label)
            if isinstance(arr, list) and arr:
                top1 = arr[0]
                engine_picks[label.lower()] = {
                    "horse_number": top1.get("horse_number"),
                    "horse_name": top1.get("horse_name", ""),
                }
                engine_top3[label.lower()] = [
                    p.get("horse_number") for p in arr[:3] if p.get("horse_number")
                ]
    except Exception as e:
        logger.warning(f"predictions failed for {race.get('race_id')}: {e}")

    # Consensus (Layer 1 top1合議)
    pick_nums = [p["horse_number"] for p in engine_picks.values() if p.get("horse_number")]
    cons_horse, cons_count, agreed = None, 0, []
    if pick_nums:
        counter = Counter(pick_nums)
        cons_horse, cons_count = counter.most_common(1)[0]
        agreed = [eng for eng, p in engine_picks.items() if p.get("horse_number") == cons_horse]

    cons_pop = pop_rank_map.get(cons_horse) if cons_horse else None

    # top3 union (Layer 2 用)
    votes_t3 = Counter()
    for top3_list in engine_top3.values():
        for h in top3_list:
            if h: votes_t3[h] += 1

    # Filters
    is_nar = bool(race.get("is_local"))
    venue = race.get("venue", "")
    total_horses = len(horse_numbers)

    # Layer 1 (v6, NAR本命厳格): 火水木 + 6-12頭 + 5-8人気 + 旧強5会場 + 2-3一致
    # clean 2ヶ月実績: n=145 / 回収率396.9% / Bootstrap CI下限225%
    is_layer1_strict = (
        is_nar
        and cons_count in (2, 3)
        and cons_pop is not None
        and LAYER1_POP_MIN <= cons_pop <= LAYER1_POP_MAX
        and venue in OLD_STRONG5
        and weekday in LAYER1_WEEKDAYS
        and LAYER1_FIELD_MIN <= total_horses <= LAYER1_FIELD_MAX
    )

    # Layer 2 (帯広中穴): 2026-04-27 無効化 (LAYER2_ENABLED=False)
    # ばんえい未学習エンジンによる偶発的数字とみなし、配信から除外
    layer2_horses = []
    if LAYER2_ENABLED and is_nar and venue in LAYER2_VENUES:
        for h, vc in votes_t3.items():
            pop = pop_rank_map.get(h)
            if pop and LAYER2_POP_MIN <= pop <= LAYER2_POP_MAX:
                layer2_horses.append({
                    "horse_number": h,
                    "horse_name": horse_map.get(h, ""),
                    "popularity": pop,
                    "vote_count": vc,
                })
        layer2_horses.sort(key=lambda x: (-x["vote_count"], x["popularity"]))
        layer2_horses = layer2_horses[:LAYER2_MAX_HORSES]
    is_layer2_obihiro = bool(layer2_horses)

    # Layer 3 (JRA S級): 週末(土日)JRA 限定、3戦略
    # - F5複勝対象: 3エンジン以上 top3 一致馬
    # - U2馬連BOX3対象: 投票TOP3頭の組合せ (3点)
    # - S1三連複1点対象: 投票TOP3頭の組合せ (1点)
    layer3_f5_horses = []      # F5複勝対象馬リスト (3eng+一致)
    layer3_top3_horses = []    # U2/S1対象 投票TOP3頭
    is_jra_weekend = not is_nar and weekday in LAYER3_WEEKDAYS
    if is_jra_weekend and votes_t3:
        # F5: 3エンジン以上 top3 一致
        for h, vc in votes_t3.items():
            if vc >= LAYER3_MIN_T3_CONS:
                layer3_f5_horses.append({
                    "horse_number": h,
                    "horse_name": horse_map.get(h, ""),
                    "popularity": pop_rank_map.get(h),
                    "vote_count": vc,
                })
        layer3_f5_horses.sort(key=lambda x: (-x["vote_count"], x.get("popularity") or 99))

        # U2/S1: 投票TOP3頭 (vote降順, pop昇順)
        ranked = sorted(votes_t3.items(),
                       key=lambda x: (-x[1], pop_rank_map.get(x[0]) or 99, x[0]))
        for h, vc in ranked[:LAYER3_T3_TOP_N]:
            layer3_top3_horses.append({
                "horse_number": h,
                "horse_name": horse_map.get(h, ""),
                "popularity": pop_rank_map.get(h),
                "vote_count": vc,
            })

    is_layer3_jra_f5 = bool(layer3_f5_horses)
    is_layer3_jra_combo = len(layer3_top3_horses) == LAYER3_T3_TOP_N

    return {
        "engine_picks": engine_picks,
        "consensus": {
            "horse_number": cons_horse,
            "horse_name": horse_map.get(cons_horse, "") if cons_horse else "",
            "agreed_engines": agreed,
            "count": cons_count,
        },
        "popularity_rank": cons_pop,
        "field_size": total_horses,
        "is_golden_strict": is_layer1_strict,        # Layer 1 (v6): NAR本命厳格 単勝
        "is_layer2_obihiro": is_layer2_obihiro,      # Layer 2: 帯広中穴 (複勝+ワイドBOX)
        "obihiro_horses": layer2_horses,              # Layer 2 中穴馬リスト
        "is_layer3_jra_f5": is_layer3_jra_f5,         # Layer 3: JRA F5複勝 (3eng+一致)
        "is_layer3_jra_combo": is_layer3_jra_combo,  # Layer 3: JRA 馬連BOX3+三連複1点 (TOP3投票)
        "jra_f5_horses": layer3_f5_horses,            # Layer 3 F5対象馬
        "jra_top3_horses": layer3_top3_horses,        # Layer 3 馬連/三連複対象馬
        "is_golden_high": False,                      # 旧 v5 互換 (deprecated)
        "is_golden_loose": False,                     # 旧 v3 互換 (deprecated)
        "pinpoint": None,                              # 旧 v5 ピンポイント (deprecated, 汚染データ由来)
    }


@bp.route("/golden-pattern/today", methods=["GET"])
def get_golden_pattern_today():
    """Return today's races with golden-pattern annotations.

    Query params:
        date: YYYYMMDD (default: today)
        race_type: jra | nar | both (default: both)

    Returns:
        { date, weekday, summary: {total, loose, strict}, races: [...] }
    """
    date_str = request.args.get("date", datetime.now().strftime("%Y%m%d"))
    race_type = request.args.get("race_type", "both")

    try:
        weekday = datetime.strptime(date_str, "%Y%m%d").weekday()
    except ValueError:
        return jsonify({"error": "invalid date format, use YYYYMMDD"}), 400

    prefetch = _load_prefetch(date_str)
    if not prefetch:
        # Fallback: load saved snapshot (preserved beyond prefetch retention)
        snapshot_path = os.path.join(SNAPSHOT_DIR, f"{date_str}.json")
        if os.path.exists(snapshot_path):
            try:
                with open(snapshot_path, 'r', encoding='utf-8') as f:
                    snap = json.load(f)
                # Re-filter by race_type if requested
                if race_type in ("jra", "nar") and snap.get("races"):
                    is_local_filter = (race_type == "nar")
                    snap["races"] = [r for r in snap["races"] if bool(r.get("is_local")) == is_local_filter]
                snap["source"] = "snapshot"
                return jsonify(snap)
            except Exception as e:
                logger.warning(f"snapshot load failed for {date_str}: {e}")
        return jsonify({
            "error": "prefetch data not available for this date",
            "date": date_str,
            "races": [],
        }), 404

    races = prefetch.get("races", [])
    if race_type == "jra":
        races = [r for r in races if not r.get("is_local")]
    elif race_type == "nar":
        races = [r for r in races if r.get("is_local")]

    # Fetch results for all races on this date (single query)
    results_by_id = _fetch_results_for_date(date_str)

    enriched = []
    summary = {
        "total": 0,
        "loose_golden": 0, "strict_golden": 0,
        "loose_finished": 0, "strict_finished": 0,
        "loose_hits": 0, "strict_hits": 0,
        "loose_profit": 0, "strict_profit": 0,
        # v5 fields (deprecated)
        "high_golden": 0, "high_finished": 0, "high_hits": 0, "high_profit": 0,
        "pinpoint_golden": 0, "pinpoint_finished": 0, "pinpoint_hits": 0, "pinpoint_profit": 0,
        # Layer 2 (帯広中穴)
        "obihiro_golden": 0, "obihiro_horses_total": 0,
        "obihiro_finished": 0, "obihiro_place_hits": 0,
        # Layer 3 (JRA S級)
        "jra_f5_golden": 0, "jra_f5_horses_total": 0,
        "jra_f5_finished": 0, "jra_f5_place_hits": 0,
        "jra_combo_golden": 0, "jra_combo_finished": 0, "jra_combo_hits": 0,
    }

    for r in races:
        eval_result = _evaluate_golden_pattern(r, weekday)
        summary["total"] += 1
        is_loose = eval_result["is_golden_loose"]
        is_strict = eval_result["is_golden_strict"]
        is_high = eval_result.get("is_golden_high", False)
        is_pinpoint = eval_result.get("pinpoint") is not None
        is_obihiro = eval_result.get("is_layer2_obihiro", False)
        if is_loose: summary["loose_golden"] += 1
        if is_strict: summary["strict_golden"] += 1
        if is_high: summary["high_golden"] += 1
        if is_pinpoint: summary["pinpoint_golden"] += 1
        if is_obihiro:
            summary["obihiro_golden"] += 1
            summary["obihiro_horses_total"] += len(eval_result.get("obihiro_horses", []))
        if eval_result.get("is_layer3_jra_f5"):
            summary["jra_f5_golden"] += 1
            summary["jra_f5_horses_total"] += len(eval_result.get("jra_f5_horses", []))
        if eval_result.get("is_layer3_jra_combo"):
            summary["jra_combo_golden"] += 1

        race_result = _build_race_result(eval_result, results_by_id.get(r.get("race_id", "")))
        if race_result and is_loose:
            summary["loose_finished"] += 1
            if race_result["did_consensus_win"]:
                summary["loose_hits"] += 1
            if race_result.get("profit_yen") is not None:
                summary["loose_profit"] += race_result["profit_yen"]
        if race_result and is_strict:
            summary["strict_finished"] += 1
            if race_result["did_consensus_win"]:
                summary["strict_hits"] += 1
            if race_result.get("profit_yen") is not None:
                summary["strict_profit"] += race_result["profit_yen"]
        if race_result and is_high:
            summary["high_finished"] += 1
            if race_result["did_consensus_win"]:
                summary["high_hits"] += 1
            if race_result.get("profit_yen") is not None:
                summary["high_profit"] += race_result["profit_yen"]
        if race_result and is_pinpoint:
            summary["pinpoint_finished"] += 1
            if race_result["did_consensus_win"]:
                summary["pinpoint_hits"] += 1
            if race_result.get("profit_yen") is not None:
                summary["pinpoint_profit"] += race_result["profit_yen"]
        # Layer 2 obihiro outcome tracking
        if race_result and is_obihiro:
            for oc in (race_result.get("obihiro_outcomes") or []):
                summary["obihiro_finished"] += 1
                if oc.get("placed"):
                    summary["obihiro_place_hits"] += 1
        # Layer 3 F5 outcome tracking
        if race_result and eval_result.get("is_layer3_jra_f5"):
            for oc in (race_result.get("f5_outcomes") or []):
                summary["jra_f5_finished"] += 1
                if oc.get("placed"):
                    summary["jra_f5_place_hits"] += 1
        # Layer 3 combo outcome tracking
        if race_result and eval_result.get("is_layer3_jra_combo"):
            summary["jra_combo_finished"] += 1
            if race_result.get("l3_combo_hit"):
                summary["jra_combo_hits"] += 1

        enriched.append({
            "race_id": r.get("race_id", ""),
            "venue": r.get("venue", ""),
            "race_number": r.get("race_number", 0),
            "race_name": r.get("race_name", ""),
            "start_time": r.get("start_time", ""),
            "is_local": bool(r.get("is_local")),
            "distance": r.get("distance", ""),
            "track_condition": r.get("track_condition", "−"),
            "total_horses": len(r.get("horse_numbers") or []),
            **eval_result,
            "result": race_result,
        })

    weekday_ja = ["月", "火", "水", "木", "金", "土", "日"][weekday]
    return jsonify({
        "date": date_str,
        "weekday": weekday_ja,
        "summary": summary,
        "races": enriched,
    })
