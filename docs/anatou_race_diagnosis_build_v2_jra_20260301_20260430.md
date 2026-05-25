# 穴党参謀AI レース診断データセット作成 2026-05-25

- input: `data\wide_rebirth_dataset_api_jra_20260301_20260430.jsonl`
- output: `data\anatou_race_diagnosis_v2_jra_20260301_20260430.jsonl`
- records: 395
- watch labels: 6
- with AI holes: 230
- with danger popular: 88

## primary_label

| label | races |
|---|---:|
| skip | 165 |
| ai_consensus | 139 |
| market_gap | 60 |
| hole_candidate | 31 |

## suggested_use

| suggested_use | races |
|---|---:|
| hole_check | 170 |
| skip | 161 |
| ai_low_rated_popular_check | 60 |
| low_priority | 4 |

## race_type

| race_type | races |
|---|---:|
| jra | 395 |

## venue top30

| venue | races |
|---|---:|
| 阪神 | 144 |
| 中山 | 132 |
| 中京 | 71 |
| 福島 | 48 |

## watch_score上位サンプル

| race | label | use | watch | gap | holes | dangers | summary |
|---|---|---|---:|---:|---:|---:|---|
| 2026-03-21 中京7R | market_gap | ai_low_rated_popular_check | 91.5 | 100.0 | 4 | 1 | 中京7R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 3番(11人気, 4基支持) / AI低評価人気 7番(2人気, AI支持0基) / AI中心 3番(4基支持) |
| 2026-04-04 中山10R | market_gap | ai_low_rated_popular_check | 90.3 | 98.0 | 3 | 2 | 中山10R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 8番(7人気, 4基支持) / AI低評価人気 3番(2人気, AI支持0基) / AI中心 6番(4基支持) |
| 2026-04-11 福島7R | market_gap | ai_low_rated_popular_check | 82.1 | 88.0 | 3 | 1 | 福島7R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 8番(8人気, 3基支持) / AI低評価人気 6番(2人気, AI支持0基) / AI中心 8番(3基支持) |
| 2026-04-11 中山3R | hole_candidate | hole_check | 79.0 | 78.0 | 3 | 0 | 中山3R / 診断=hole_candidate / 用途=hole_check / AI穴馬 9番(9人気, 4基支持) / AI中心 9番(4基支持) |
| 2026-03-14 中山8R | hole_candidate | hole_check | 76.2 | 78.0 | 3 | 0 | 中山8R / 診断=hole_candidate / 用途=hole_check / AI穴馬 14番(11人気, 4基支持) / AI中心 14番(4基支持) |
| 2026-04-11 福島3R | market_gap | ai_low_rated_popular_check | 71.7 | 72.0 | 2 | 2 | 福島3R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 1番(8人気, 3基支持) / AI低評価人気 11番(2人気, AI支持0基) / AI中心 1番(3基支持) |
| 2026-04-19 中山11R | market_gap | ai_low_rated_popular_check | 67.8 | 62.0 | 2 | 1 | 中山11R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 11番(8人気, 3基支持) / AI低評価人気 12番(2人気, AI支持0基) / AI中心 11番(3基支持) |
| 2026-04-04 阪神5R | market_gap | ai_low_rated_popular_check | 67.7 | 62.0 | 2 | 1 | 阪神5R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 17番(8人気, 4基支持) / AI低評価人気 6番(3人気, AI支持0基) / AI中心 16番(4基支持) |
| 2026-04-12 阪神1R | market_gap | ai_low_rated_popular_check | 67.6 | 62.0 | 2 | 1 | 阪神1R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 3番(6人気, 4基支持) / AI低評価人気 6番(3人気, AI支持0基) / AI中心 3番(4基支持) |
| 2026-03-14 中京9R | market_gap | ai_low_rated_popular_check | 66.9 | 62.0 | 2 | 1 | 中京9R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 2番(8人気, 3基支持) / AI低評価人気 4番(3人気, AI支持0基) / AI中心 8番(4基支持) |
| 2026-03-28 中山10R | market_gap | ai_low_rated_popular_check | 66.9 | 62.0 | 2 | 1 | 中山10R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 6番(9人気, 3基支持) / AI低評価人気 2番(3人気, AI支持0基) / AI中心 10番(4基支持) |
| 2026-04-19 福島6R | market_gap | ai_low_rated_popular_check | 66.9 | 62.0 | 2 | 1 | 福島6R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 3番(10人気, 3基支持) / AI低評価人気 6番(2人気, AI支持0基) / AI中心 5番(4基支持) |
| 2026-04-04 中山8R | market_gap | ai_low_rated_popular_check | 66.8 | 62.0 | 2 | 1 | 中山8R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 9番(7人気, 4基支持) / AI低評価人気 7番(1人気, AI支持0基) / AI中心 9番(4基支持) |
| 2026-04-12 阪神9R | market_gap | ai_low_rated_popular_check | 66.8 | 62.0 | 2 | 1 | 阪神9R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 7番(12人気, 4基支持) / AI低評価人気 13番(2人気, AI支持0基) / AI中心 7番(4基支持) |
| 2026-04-18 中山8R | market_gap | ai_low_rated_popular_check | 66.8 | 62.0 | 2 | 1 | 中山8R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 1番(9人気, 3基支持) / AI低評価人気 3番(2人気, AI支持0基) / AI中心 14番(4基支持) |
| 2026-04-18 阪神11R | market_gap | ai_low_rated_popular_check | 66.2 | 62.0 | 2 | 1 | 阪神11R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 13番(12人気, 3基支持) / AI低評価人気 1番(2人気, AI支持0基) / AI中心 3番(3基支持) |
| 2026-04-05 阪神3R | market_gap | ai_low_rated_popular_check | 66.0 | 62.0 | 2 | 1 | 阪神3R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 6番(6人気, 3基支持) / AI低評価人気 13番(3人気, AI支持0基) / AI中心 6番(3基支持) |
| 2026-03-21 中京6R | market_gap | ai_low_rated_popular_check | 64.5 | 62.0 | 2 | 1 | 中京6R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 1番(7人気, 3基支持) / AI低評価人気 8番(3人気, AI支持0基) / AI中心 1番(3基支持) |
| 2026-03-22 中山12R | market_gap | ai_low_rated_popular_check | 64.5 | 62.0 | 2 | 1 | 中山12R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 4番(7人気, 3基支持) / AI低評価人気 14番(3人気, AI支持0基) / AI中心 4番(3基支持) |
| 2026-03-14 阪神1R | market_gap | ai_low_rated_popular_check | 63.6 | 62.0 | 2 | 1 | 阪神1R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 13番(8人気, 4基支持) / AI低評価人気 4番(1人気, AI支持0基) / AI中心 1番(4基支持) |

