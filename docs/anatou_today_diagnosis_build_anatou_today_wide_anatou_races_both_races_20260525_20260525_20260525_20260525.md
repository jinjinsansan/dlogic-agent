# 穴党参謀AI レース診断データセット作成 2026-05-25

- input: `E:\dev\Cusor\dlogic-agent\data\anatou_today_wide_anatou_races_both_races_20260525_20260525_20260525.jsonl`
- output: `E:\dev\Cusor\dlogic-agent\data\anatou_today_diagnosis_anatou_today_wide_anatou_races_both_races_20260525_20260525_20260525_20260525.jsonl`
- records: 50
- watch labels: 6
- with AI holes: 31
- with danger popular: 14

## primary_label

| label | races |
|---|---:|
| skip | 19 |
| ai_consensus | 15 |
| market_gap | 13 |
| hole_candidate | 3 |

## suggested_use

| suggested_use | races |
|---|---:|
| skip | 19 |
| hole_check | 18 |
| ai_low_rated_popular_check | 13 |

## race_type

| race_type | races |
|---|---:|
| nar | 50 |

## venue top30

| venue | races |
|---|---:|
| 名古屋 | 12 |
| 盛岡 | 12 |
| 金沢 | 12 |
| 浦和 | 10 |
| 帯広 | 4 |

## watch_score上位サンプル

| race | label | use | watch | gap | holes | dangers | summary |
|---|---|---|---:|---:|---:|---:|---|
| 2026-05-25 帯広4R | market_gap | ai_low_rated_popular_check | 83.8 | 98.0 | 3 | 2 | 帯広4R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 2番(8人気, 3基支持) / AI低評価人気 8番(1人気, AI支持0基) / AI中心 1番(3基支持) |
| 2026-05-25 名古屋8R | market_gap | ai_low_rated_popular_check | 83.8 | 88.0 | 3 | 1 | 名古屋8R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 6番(8人気, 4基支持) / AI低評価人気 9番(1人気, AI支持0基) / AI中心 6番(4基支持) |
| 2026-05-25 金沢8R | market_gap | ai_low_rated_popular_check | 76.6 | 82.0 | 2 | 3 | 金沢8R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 2番(7人気, 4基支持) / AI低評価人気 8番(1人気, AI支持0基) / AI中心 2番(4基支持) |
| 2026-05-25 名古屋1R | hole_candidate | hole_check | 76.5 | 78.0 | 3 | 0 | 名古屋1R / 診断=hole_candidate / 用途=hole_check / AI穴馬 4番(9人気, 4基支持) / AI中心 3番(4基支持) |
| 2026-05-25 名古屋4R | hole_candidate | hole_check | 75.6 | 78.0 | 3 | 0 | 名古屋4R / 診断=hole_candidate / 用途=hole_check / AI穴馬 3番(9人気, 3基支持) / AI中心 3番(3基支持) |
| 2026-05-25 名古屋12R | market_gap | ai_low_rated_popular_check | 72.3 | 72.0 | 2 | 2 | 名古屋12R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 1番(10人気, 3基支持) / AI低評価人気 7番(1人気, AI支持0基) / AI中心 3番(4基支持) |
| 2026-05-25 帯広10R | market_gap | ai_low_rated_popular_check | 68.5 | 72.0 | 2 | 2 | 帯広10R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 5番(6人気, 4基支持) / AI低評価人気 8番(1人気, AI支持0基) / AI中心 5番(4基支持) |
| 2026-05-25 帯広2R | market_gap | ai_low_rated_popular_check | 66.9 | 72.0 | 2 | 2 | 帯広2R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 1番(5人気, 3基支持) / AI低評価人気 8番(1人気, AI支持0基) / AI中心 1番(3基支持) |
| 2026-05-25 名古屋6R | hole_candidate | hole_check | 62.2 | 52.0 | 2 | 0 | 名古屋6R / 診断=hole_candidate / 用途=hole_check / AI穴馬 9番(7人気, 3基支持) / AI中心 10番(4基支持) |
| 2026-05-25 名古屋3R | ai_consensus | hole_check | 59.4 | 52.0 | 2 | 0 | 名古屋3R / 診断=ai_consensus / 用途=hole_check / AI穴馬 3番(7人気, 4基支持) / AI中心 1番(4基支持) |
| 2026-05-25 帯広8R | ai_consensus | hole_check | 53.9 | 52.0 | 2 | 0 | 帯広8R / 診断=ai_consensus / 用途=hole_check / AI穴馬 1番(8人気, 3基支持) / AI中心 1番(3基支持) |
| 2026-05-25 盛岡8R | market_gap | ai_low_rated_popular_check | 51.0 | 36.0 | 1 | 1 | 盛岡8R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 3番(10人気, 4基支持) / AI低評価人気 8番(3人気, AI支持0基) / AI中心 3番(4基支持) |
| 2026-05-25 盛岡3R | market_gap | ai_low_rated_popular_check | 50.0 | 36.0 | 1 | 1 | 盛岡3R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 1番(8人気, 4基支持) / AI低評価人気 6番(3人気, AI支持0基) / AI中心 4番(4基支持) |
| 2026-05-25 名古屋11R | market_gap | ai_low_rated_popular_check | 49.2 | 36.0 | 1 | 1 | 名古屋11R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 3番(9人気, 4基支持) / AI低評価人気 1番(2人気, AI支持0基) / AI中心 3番(4基支持) |
| 2026-05-25 名古屋5R | market_gap | ai_low_rated_popular_check | 49.0 | 36.0 | 1 | 1 | 名古屋5R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 1番(10人気, 4基支持) / AI低評価人気 7番(1人気, AI支持0基) / AI中心 1番(4基支持) |
| 2026-05-25 名古屋9R | market_gap | ai_low_rated_popular_check | 49.0 | 36.0 | 1 | 1 | 名古屋9R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 1番(6人気, 3基支持) / AI低評価人気 10番(1人気, AI支持0基) / AI中心 2番(4基支持) |
| 2026-05-25 金沢3R | market_gap | ai_low_rated_popular_check | 48.5 | 36.0 | 1 | 1 | 金沢3R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 4番(7人気, 4基支持) / AI低評価人気 5番(3人気, AI支持0基) / AI中心 4番(4基支持) |
| 2026-05-25 浦和10R | ai_consensus | hole_check | 47.5 | 26.0 | 1 | 0 | 浦和10R / 診断=ai_consensus / 用途=hole_check / AI穴馬 6番(9人気, 4基支持) / AI中心 4番(4基支持) |
| 2026-05-25 盛岡7R | market_gap | ai_low_rated_popular_check | 47.4 | 36.0 | 1 | 1 | 盛岡7R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 5番(9人気, 4基支持) / AI低評価人気 9番(3人気, AI支持0基) / AI中心 5番(4基支持) |
| 2026-05-25 浦和11R | ai_consensus | hole_check | 47.1 | 26.0 | 1 | 0 | 浦和11R / 診断=ai_consensus / 用途=hole_check / AI穴馬 2番(10人気, 4基支持) / AI中心 4番(5基支持) |

