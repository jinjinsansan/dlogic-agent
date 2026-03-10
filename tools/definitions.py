"""Claude API tool definitions for the Dlogic agent."""

TOOLS = [
    {
        "name": "get_today_races",
        "description": "今日（または指定日）のJRAまたは地方競馬のレース一覧を取得します。レース番号、レース名、競馬場、距離、出走頭数を返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "対象日付 (YYYYMMDD形式)。省略時は今日の日付。"
                },
                "race_type": {
                    "type": "string",
                    "enum": ["jra", "nar"],
                    "description": "レースの種類。jra=中央競馬、nar=地方競馬"
                },
                "venue": {
                    "type": "string",
                    "description": "競馬場名でフィルタ（例: '大井', '中山'）。省略時は全競馬場。"
                }
            },
            "required": ["race_type"]
        }
    },
    {
        "name": "get_race_entries",
        "description": "特定レースの出馬表を取得します。馬名、騎手、枠番、馬番、性齢、斤量が返されます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "netkeiba.comのレースID（例: '202406050811'）"
                },
                "race_type": {
                    "type": "string",
                    "enum": ["jra", "nar"],
                    "description": "レースの種類。jra=中央競馬、nar=地方競馬"
                }
            },
            "required": ["race_id", "race_type"]
        }
    },
    {
        "name": "get_predictions",
        "description": "AIによるレース予想を取得します。複数の分析エンジンの予想上位5頭を返します。JRA・地方競馬どちらも対応。出馬表データ（horses, horse_numbers等）が必要なので、先にget_race_entriesで取得してから呼び出してください。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "netkeiba.comのレースID"
                },
                "horses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "出走馬名のリスト（馬番順）"
                },
                "horse_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "馬番のリスト"
                },
                "venue": {
                    "type": "string",
                    "description": "競馬場名（例: '中山'）"
                },
                "race_number": {
                    "type": "integer",
                    "description": "レース番号"
                },
                "jockeys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "騎手名のリスト（馬番順）"
                },
                "posts": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "枠番のリスト（馬番順）"
                },
                "distance": {
                    "type": "string",
                    "description": "距離（例: '芝2000m'）"
                },
                "track_condition": {
                    "type": "string",
                    "description": "馬場状態（良/稍重/重/不良）"
                }
            },
            "required": ["race_id", "horses", "horse_numbers", "venue", "race_number"]
        }
    },
    {
        "name": "get_realtime_odds",
        "description": "指定レースのリアルタイム単勝オッズを取得します。馬番ごとの現在オッズを返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "netkeiba.comのレースID（例: '202406050811'）"
                },
                "race_type": {
                    "type": "string",
                    "enum": ["jra", "nar"],
                    "description": "レースの種類。jra=中央競馬、nar=地方競馬"
                }
            },
            "required": ["race_id", "race_type"]
        }
    },
    {
        "name": "search_horse",
        "description": "馬名で検索し、過去5走の成績を取得します。日付、競馬場、距離、着順、騎手、タイムを返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "horse_name": {
                    "type": "string",
                    "description": "検索する馬の名前（例: 'イクイノックス'）"
                }
            },
            "required": ["horse_name"]
        }
    },
    {
        "name": "get_race_flow",
        "description": "レースの展開予想を取得します。ペース予測、各馬の脚質分類、展開適性スコア、シミュレーション着順予測を返します。「展開は？」「どんなレースになりそう？」等の質問で必ず使ってください。race_idだけで呼べます（出馬表データは自動補完されます）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {"type": "string", "description": "レースID（get_race_entriesで取得したもの）"}
            },
            "required": ["race_id"]
        }
    },
    {
        "name": "get_jockey_analysis",
        "description": "出走騎手の枠別複勝率を分析します。各騎手が内枠/中枠/外枠でどのくらいの複勝率か返します。「騎手の成績は？」「この枠で騎手はどう？」「騎手分析して」等の質問で必ず使ってください。race_idだけで呼べます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {"type": "string", "description": "レースID（get_race_entriesで取得したもの）"}
            },
            "required": ["race_id"]
        }
    },
    {
        "name": "get_bloodline_analysis",
        "description": "出走馬の血統分析（父・母父の産駒成績）を取得します。「血統的にはどう？」「この馬の血統は？」等の質問で必ず使ってください。race_idだけで呼べます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {"type": "string", "description": "レースID（get_race_entriesで取得したもの）"}
            },
            "required": ["race_id"]
        }
    },
    {
        "name": "get_recent_runs",
        "description": "出走馬全頭の直近5走の成績を取得します。各馬の着順、競馬場、距離、騎手、オッズ、脚質タイプを返します。「過去の成績は？」「直近の調子は？」等の質問で必ず使ってください。race_idだけで呼べます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {"type": "string", "description": "レースID（get_race_entriesで取得したもの）"}
            },
            "required": ["race_id"]
        }
    },
]
