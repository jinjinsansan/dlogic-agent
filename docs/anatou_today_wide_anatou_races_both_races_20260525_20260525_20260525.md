# 穴党参謀AI ワイド再構築 API再生成データセット 2026-05-25

- input: `E:\dev\Cusor\dlogic-agent\data\anatou_races_both_races_20260525_20260525.json`
- output: `E:\dev\Cusor\dlogic-agent\data\anatou_today_wide_anatou_races_both_races_20260525_20260525_20260525.jsonl`
- api_url: `http://localhost:8011`

## 件数

- input races: 60
- output records: 50
- api errors: 0
- NLogicあり: 50 (100.0%)
- top5あり: 50 (100.0%)
- all available engines top5: 45 (90.0%)
- wide払戻あり: 0 (0.0%)

## race_type

| race_type | records |
|---|---:|
| nar | 50 |

## engine_count

| engine_count | records |
|---|---:|
| 4 | 40 |
| 5 | 10 |

## 注意

- これは現在のバックエンドモデルで過去レースを再予測したデータ。
- 当時の配信時点モデルではないため、実運用検証とは区別する。
- ワイド払戻は既存wide_rebirth datasetから突合している。

