# 穴党参謀AI レース診断ラベル妥当性検証 2026-05-25

- diagnosis: `data\anatou_race_diagnosis_jra_20260301_20260430.jsonl`
- race_dataset: `data\wide_rebirth_dataset_api_jra_20260301_20260430.jsonl`
- diagnosis rows: 395
- race rows: 395
- high wide threshold: 1000
- super high wide threshold: 3000

## primary_label 件数

| label | races |
|---|---:|
| market_gap | 159 |
| ai_consensus | 139 |
| hole_candidate | 97 |

## suggested_use 件数

| suggested_use | races |
|---|---:|
| hole_check | 235 |
| danger_popular_check | 159 |
| skip | 1 |

## primary_label別

| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| market_gap | 159 | 159 | 556 | 15.3% | 189 | 55.0% | 3231 | 75.5% | 28.9% | 79.0 |
| hole_candidate | 97 | 97 | 351 | 14.5% | 0 | 0.0% | 3051 | 66.0% | 23.7% | 70.3 |
| ai_consensus | 139 | 139 | 293 | 19.1% | 0 | 0.0% | 2225 | 48.2% | 22.3% | 52.9 |

## suggested_use別

| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| danger_popular_check | 159 | 159 | 556 | 15.3% | 189 | 55.0% | 3231 | 75.5% | 28.9% | 79.0 |
| hole_check | 235 | 235 | 644 | 16.6% | 0 | 0.0% | 2574 | 55.7% | 23.0% | 60.2 |
| skip | 1 | 1 | 0 | 0.0% | 0 | 0.0% | 180 | 0.0% | 0.0% | 28.9 |

## watch_score帯別

| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| watch_80+ | 89 | 89 | 376 | 16.0% | 111 | 55.0% | 3351 | 73.0% | 31.5% | 86.3 |
| watch_60_79 | 200 | 200 | 633 | 15.2% | 77 | 54.5% | 2920 | 68.5% | 25.5% | 69.0 |
| watch_40_59 | 97 | 97 | 183 | 17.5% | 1 | 100.0% | 2334 | 46.4% | 20.6% | 50.7 |
| watch_0_39 | 9 | 9 | 8 | 50.0% | 0 | 0.0% | 1150 | 44.4% | 11.1% | 37.8 |

## 競馬場別 top20

| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 福島 | 48 | 48 | 167 | 15.6% | 38 | 47.4% | 2716 | 72.9% | 29.2% | 74.9 |
| 中山 | 132 | 132 | 395 | 16.5% | 61 | 60.7% | 2979 | 63.6% | 24.2% | 67.3 |
| 阪神 | 144 | 144 | 406 | 15.3% | 55 | 54.5% | 2856 | 61.8% | 25.7% | 64.3 |
| 中京 | 71 | 71 | 232 | 16.8% | 35 | 54.3% | 2592 | 60.6% | 23.9% | 70.3 |

## 読み方

- `hole_top3`: AI穴馬がワイド払戻から推定した3着内に入った率。
- `danger_miss`: 危険人気馬が推定3着内に入らなかった率。高いほど診断としては良い。
- `high_wide`: レース内の最大ワイド払戻が閾値以上だった率。
- この検証は買い目ROIではなく、診断コンテンツとして意味があるかを見るもの。

