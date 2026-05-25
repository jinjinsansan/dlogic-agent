# 穴党参謀AI レース診断ラベル妥当性検証 2026-05-25

- diagnosis: `data\anatou_race_diagnosis_v2_jra_20260301_20260430.jsonl`
- race_dataset: `data\wide_rebirth_dataset_api_jra_20260301_20260430.jsonl`
- diagnosis rows: 395
- race rows: 395
- high wide threshold: 1000
- super high wide threshold: 3000

## primary_label 件数

| label | races |
|---|---:|
| skip | 165 |
| ai_consensus | 139 |
| market_gap | 60 |
| hole_candidate | 31 |

## suggested_use 件数

| suggested_use | races |
|---|---:|
| hole_check | 170 |
| skip | 161 |
| ai_low_rated_popular_check | 60 |
| low_priority | 4 |

## primary_label別

| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| market_gap | 60 | 60 | 82 | 17.1% | 66 | 54.5% | 2965 | 71.7% | 26.7% | 56.0 |
| ai_consensus | 139 | 139 | 151 | 13.9% | 0 | 0.0% | 2876 | 64.7% | 28.1% | 44.2 |
| hole_candidate | 31 | 31 | 59 | 11.9% | 0 | 0.0% | 3276 | 64.5% | 29.0% | 59.1 |
| skip | 165 | 165 | 0 | 0.0% | 30 | 63.3% | 2665 | 59.4% | 21.8% | 27.1 |

## suggested_use別

| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ai_low_rated_popular_check | 60 | 60 | 82 | 17.1% | 66 | 54.5% | 2965 | 71.7% | 26.7% | 56.0 |
| hole_check | 170 | 170 | 210 | 13.3% | 0 | 0.0% | 2949 | 64.7% | 28.2% | 46.9 |
| skip | 161 | 161 | 0 | 0.0% | 24 | 66.7% | 2695 | 59.6% | 22.4% | 26.9 |
| low_priority | 4 | 4 | 0 | 0.0% | 6 | 50.0% | 1450 | 50.0% | 0.0% | 37.2 |

## watch_score帯別

| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| watch_40_59 | 187 | 187 | 203 | 15.3% | 43 | 58.1% | 2924 | 67.4% | 27.8% | 45.7 |
| watch_80+ | 3 | 3 | 10 | 10.0% | 4 | 25.0% | 1670 | 66.7% | 0.0% | 88.0 |
| watch_60_79 | 38 | 38 | 77 | 13.0% | 19 | 52.6% | 3248 | 63.2% | 28.9% | 64.2 |
| watch_0_39 | 167 | 167 | 2 | 0.0% | 30 | 63.3% | 2657 | 59.3% | 22.2% | 27.3 |

## 競馬場別 top20

| group | races | outcome | hole_n | hole_top3 | danger_n | danger_miss | avg_max_wide | high_wide | super_high | avg_watch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 福島 | 48 | 48 | 41 | 7.3% | 16 | 50.0% | 2716 | 72.9% | 29.2% | 43.1 |
| 中山 | 132 | 132 | 98 | 13.3% | 32 | 59.4% | 2979 | 63.6% | 24.2% | 40.0 |
| 阪神 | 144 | 144 | 100 | 15.0% | 33 | 57.6% | 2856 | 61.8% | 25.7% | 39.1 |
| 中京 | 71 | 71 | 53 | 20.8% | 15 | 60.0% | 2592 | 60.6% | 23.9% | 39.9 |

## 読み方

- `hole_top3`: AI穴馬がワイド払戻から推定した3着内に入った率。
- `danger_miss`: 危険人気馬が推定3着内に入らなかった率。高いほど診断としては良い。
- `high_wide`: レース内の最大ワイド払戻が閾値以上だった率。
- この検証は買い目ROIではなく、診断コンテンツとして意味があるかを見るもの。

