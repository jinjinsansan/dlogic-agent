# 穴党参謀AI ワイド再構築 API再生成データセット 2026-05-25

- input: `data\5eng_races_jra_20260301_20260430.json`
- output: `data\wide_rebirth_dataset_api_jra_test20.jsonl`
- api_url: `http://127.0.0.1:8010`

## 件数

- input races: 20
- output records: 20
- api errors: 0
- NLogicあり: 0 (0.0%)
- top5あり: 20 (100.0%)
- all available engines top5: 20 (100.0%)
- wide払戻あり: 0 (0.0%)

## race_type

| race_type | records |
|---|---:|
| jra | 20 |

## engine_count

| engine_count | records |
|---|---:|
| 3 | 20 |

## 注意

- これは現在のバックエンドモデルで過去レースを再予測したデータ。
- 当時の配信時点モデルではないため、実運用検証とは区別する。
- ワイド払戻は既存wide_rebirth datasetから突合している。

