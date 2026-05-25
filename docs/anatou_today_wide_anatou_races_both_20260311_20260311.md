# 穴党参謀AI ワイド再構築 API再生成データセット 2026-05-25

- input: `data\anatou_races_both_20260311.json`
- output: `E:\dev\Cusor\dlogic-agent\data\anatou_today_wide_anatou_races_both_20260311_20260311.jsonl`
- api_url: `http://localhost:8011`

## 件数

- input races: 3
- output records: 3
- api errors: 0
- NLogicあり: 3 (100.0%)
- top5あり: 3 (100.0%)
- all available engines top5: 3 (100.0%)
- wide払戻あり: 3 (100.0%)

## race_type

| race_type | records |
|---|---:|
| nar | 3 |

## engine_count

| engine_count | records |
|---|---:|
| 5 | 3 |

## 注意

- これは現在のバックエンドモデルで過去レースを再予測したデータ。
- 当時の配信時点モデルではないため、実運用検証とは区別する。
- ワイド払戻は既存wide_rebirth datasetから突合している。

