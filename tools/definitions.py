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
                    "description": "レースID（例: '202406050811'）"
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
        "description": "AIによるレース予想を取得します。複数の分析エンジン（Dlogic/Ilogic/ViewLogic/MetaLogic）の予想上位5頭を返します。JRA・地方競馬どちらも対応。race_idだけで呼べます（出馬表データは自動補完されます）。先にget_race_entriesで出馬表を取得してから呼んでください。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "レースID（get_race_entriesで取得したもの）"
                }
            },
            "required": ["race_id"]
        }
    },
    {
        "name": "get_race_results",
        "description": "終了済みレースの確定結果（着順・払戻）を取得します。1着〜全着順、単勝払戻金額を返します。レースがまだ終わっていない場合はエラーになります。「結果は？」「何着だった？」「勝ったのは？」等の質問で使ってください。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "レースID（例: '202406050811'）"
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
        "name": "get_realtime_odds",
        "description": "指定レースのリアルタイム単勝オッズを取得します。馬番ごとの現在オッズを返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "レースID（例: '202406050811'）"
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
        "name": "get_horse_weights",
        "description": "指定レースの馬体重（当日計量）を取得します。馬番ごとの体重(kg)と前走比増減を返します。馬体重はレース当日の朝〜昼に発表されるため、前日以前は取得できません。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "レースID（例: '202406050811'）"
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
        "name": "get_training_comments",
        "description": "指定JRAレースの調教評価を取得します。各馬の調教短評（例:好調子、気配平凡）、評価ランク（A〜D）、詳細コメントを返します。JRA限定（地方競馬には対応していません）。重要：取得した原文をそのまま出力せず、必ず自分の言葉で要約・言い換えてユーザーに伝えてください。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "レースID（例: '202406050811'）"
                }
            },
            "required": ["race_id"]
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
    {
        "name": "record_user_prediction",
        "description": "ユーザーの本命馬（みんなの予想）を記録します。ユーザーが自発的に本命を伝えてきた場合にこのツールで記録してください。お前から本命を聞くな（システムが自動で聞く）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "レースID"
                },
                "horse_number": {
                    "type": "integer",
                    "description": "本命馬の馬番"
                },
                "horse_name": {
                    "type": "string",
                    "description": "本命馬の馬名"
                },
                "race_name": {
                    "type": "string",
                    "description": "レース名（省略可）"
                },
                "venue": {
                    "type": "string",
                    "description": "競馬場名（省略可）"
                }
            },
            "required": ["race_id", "horse_number", "horse_name"]
        }
    },
    {
        "name": "check_user_prediction",
        "description": "ユーザーが指定レースの本命を既に登録済みか確認します。ユーザーが本命を伝えてきた時に重複チェックとして使ってください。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "レースID"
                }
            },
            "required": ["race_id"]
        }
    },
    {
        "name": "get_my_stats",
        "description": "ユーザー自身の「みんなの予想」成績を取得します。的中率、回収率、連勝数、最高配当、直近の予想結果を返します。「俺の成績は？」「的中率は？」「回収率見せて」等の質問で使ってください。",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_prediction_ranking",
        "description": "「みんなの予想」の回収率ランキングを取得します。全ユーザーの中で回収率上位のランキングを返します。「ランキング見せて」「みんなの成績は？」「誰が一番当たってる？」等の質問で使ってください。",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "表示人数（デフォルト10）"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_odds_probability",
        "description": "出走馬全頭の予測勝率・予測複勝率をオッズから算出します。オッズベースの統計的な勝率・複勝率を返します。出馬表を見せた後に「予測勝率も見るか？」と提案してください。race_idだけで呼べます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "レースID（get_race_entriesで取得したもの）"
                }
            },
            "required": ["race_id"]
        }
    },
    {
        "name": "get_engine_stats",
        "description": "予想エンジンの的中率データを取得します。Dlogic/Ilogic/ViewLogic/MetaLogicの各エンジンの単勝的中率・複勝的中率を返します。「エンジンの的中率は？」「どのエンジンが当たる？」「予想精度は？」等の質問で使ってください。",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "集計期間（日数）。デフォルト30日。90や365も可。"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_stable_comments",
        "description": "指定レースの関係者情報（陣営の状態・意気込み）を取得します。各馬の状態評価、印、陣営の見解を返します。JRA・地方競馬どちらも対応。「関係者情報は？」「陣営のコメントは？」「関係者の話は？」等の質問で使ってください。【絶対厳守】取得データの原文・引用符付き転載は禁止。必ず自分の分析・要約として「〜の状態は良さそう」「陣営は距離適性に自信あり」のように、お前自身の言葉で伝えろ。一字一句の引用は絶対にするな。",
        "input_schema": {
            "type": "object",
            "properties": {
                "race_id": {
                    "type": "string",
                    "description": "レースID（get_race_entriesで取得したもの）"
                }
            },
            "required": ["race_id"]
        }
    },
    {
        "name": "send_inquiry",
        "description": "ユーザーからの問い合わせ・不具合報告・要望を運営に送信します。ユーザーが「問い合わせ」「エラー報告」「要望」「バグ」「おかしい」「動かない」等の意図を示した場合に使ってください。送信前にユーザーに内容を確認すること。",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["bug", "request", "question", "other"],
                    "description": "問い合わせ種別。bug=不具合報告、request=要望、question=質問、other=その他"
                },
                "summary": {
                    "type": "string",
                    "description": "問い合わせ内容の要約（1-2文）"
                },
                "detail": {
                    "type": "string",
                    "description": "詳細な内容（ユーザーの発言を含む）"
                }
            },
            "required": ["category", "summary"]
        }
    },
]
