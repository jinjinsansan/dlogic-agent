# 穴党参謀AI ワイド再構築 データセット作成 2026-05-25

- 対象期間: 2026-03-01 〜 2026-05-25
- 出力: `E:\dev\Cusor\dlogic-agent\data\wide_rebirth_dataset_20260301_20260525_existing.jsonl`
- source: `supabase_existing`

## 条件

- min_engines: 3
- require_result: True
- require_wide: True
- require_odds: False
- require_top5: False
- require_all_top5: False
- require_nlogic: False

## 件数

- raw engine races: 4,570
- dataset records: 2,903
- resultあり: 2,903 (100.0%)
- wide払戻あり: 2,903 (100.0%)
- 人気あり: 2,206 (76.0%)
- top5あり: 1,056 (36.4%)
- available engines all top5: 949 (32.7%)
- nlogicあり: 0 (0.0%)

## race_type

| race_type | records |
|---|---:|
| nar | 2,220 |
| jra | 683 |

## engine_count

| engine_count | records |
|---|---:|
| 4 | 2,833 |
| 3 | 70 |

## month

| month | records |
|---|---:|
| 2026-05 | 1,126 |
| 2026-03 | 895 |
| 2026-04 | 882 |

## 判断

- このJSONLは既存DBの実態を固定するためのもの。
- NLogicは既存データにないため、5エンジン検証には別途バックエンドAPI再生成データセットが必要。
- top5不足のレースがあるため、top5戦略の本検証では `require_top5` またはAPI再生成版を使う。

