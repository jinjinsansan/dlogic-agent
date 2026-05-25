# 穴党参謀AI ワイド再構築 API再生成データセット 2026-05-25

- input: `data\5eng_races_nar_20260301_20260430.json`
- output: `data\wide_rebirth_dataset_api_nar_20260301_20260430.jsonl`
- api_url: `http://127.0.0.1:8011`

## 件数

- input races: 2,324
- output records: 1,343
- api errors: 0
- NLogicあり: 1,343 (100.0%)
- top5あり: 1,341 (99.9%)
- all available engines top5: 1,194 (88.9%)
- wide払戻あり: 1,343 (100.0%)

## race_type

| race_type | records |
|---|---:|
| nar | 1,343 |

## engine_count

| engine_count | records |
|---|---:|
| 4 | 1,187 |
| 5 | 156 |

## 注意

- これは現在のバックエンドモデルで過去レースを再予測したデータ。
- 当時の配信時点モデルではないため、実運用検証とは区別する。
- ワイド払戻は既存wide_rebirth datasetから突合している。

