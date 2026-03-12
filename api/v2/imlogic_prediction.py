"""
IMLogic予想API — ユーザーカスタムウェイトで予想を実行
認証不要・dlogic-agentのツールから呼び出す用途
"""
from fastapi import APIRouter, HTTPException
from typing import List, Optional, Dict
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["imlogic_prediction"])


class IMLogicPredictionRequest(BaseModel):
    race_id: str
    horses: List[str]
    horse_numbers: List[int]
    jockeys: List[str]
    posts: List[int]
    venue: str = ""
    race_number: int = 0
    distance: str = ""
    track_condition: str = "良"
    race_name: str = ""
    # IMLogic固有パラメータ
    horse_weight: int = 70
    jockey_weight: int = 30
    item_weights: Optional[Dict[str, float]] = None


DEFAULT_ITEM_WEIGHTS = {
    "1_distance_aptitude": 8.33,
    "2_bloodline_evaluation": 8.33,
    "3_jockey_compatibility": 8.33,
    "4_trainer_evaluation": 8.33,
    "5_track_aptitude": 8.33,
    "6_weather_aptitude": 8.33,
    "7_popularity_factor": 8.33,
    "8_weight_impact": 8.33,
    "9_horse_weight_impact": 8.33,
    "10_corner_specialist": 8.33,
    "11_margin_analysis": 8.33,
    "12_time_index": 8.37,
}


@router.post("/imlogic")
async def get_imlogic_prediction(request: IMLogicPredictionRequest):
    """
    IMLogicエンジンでユーザーカスタムウェイトの予想を実行。
    horse_weight + jockey_weight = 100、item_weightsの合計 = 100 が必要。
    """
    # バリデーション
    if request.horse_weight + request.jockey_weight != 100:
        raise HTTPException(
            status_code=400,
            detail=f"horse_weight + jockey_weight must equal 100 (got {request.horse_weight + request.jockey_weight})"
        )

    item_weights = request.item_weights or DEFAULT_ITEM_WEIGHTS
    weights_sum = sum(item_weights.values())
    if not (99.9 <= weights_sum <= 100.1):
        raise HTTPException(
            status_code=400,
            detail=f"item_weights must sum to 100 (got {weights_sum:.2f})"
        )

    # レースデータ組み立て
    race_data = {
        "venue": request.venue,
        "race_number": request.race_number,
        "race_name": request.race_name,
        "horses": request.horses,
        "jockeys": request.jockeys,
        "posts": request.posts,
        "horse_numbers": request.horse_numbers,
        "distance": request.distance,
        "track_condition": request.track_condition,
    }

    try:
        from services.imlogic_engine import IMLogicEngine
        engine = IMLogicEngine()

        result = engine.analyze_race(
            race_data=race_data,
            horse_weight=request.horse_weight,
            jockey_weight=request.jockey_weight,
            item_weights=item_weights,
        )

        # dlogic-agentが使いやすい形式に変換: 馬番のランキング
        rankings = []
        for entry in result.get("results", []):
            if entry.get("data_status") == "ok" and entry.get("total_score") is not None:
                rankings.append({
                    "rank": entry["rank"],
                    "horse_number": entry["horse_number"],
                    "horse_name": entry["horse"],
                    "total_score": entry["total_score"],
                    "horse_score": entry["horse_score"],
                    "jockey_score": entry["jockey_score"],
                })

        return {
            "race_id": request.race_id,
            "engine": "imlogic",
            "settings": {
                "horse_weight": request.horse_weight,
                "jockey_weight": request.jockey_weight,
                "item_weights": item_weights,
            },
            "rankings": rankings,
            "total_horses": len(request.horses),
            "ranked_horses": len(rankings),
        }

    except Exception as e:
        logger.error(f"IMLogic prediction error ({request.race_id}): {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"IMLogic error: {str(e)}")
