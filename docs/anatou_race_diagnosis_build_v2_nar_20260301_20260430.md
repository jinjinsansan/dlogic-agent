# 穴党参謀AI レース診断データセット作成 2026-05-25

- input: `data\wide_rebirth_dataset_api_nar_20260301_20260430.jsonl`
- output: `data\anatou_race_diagnosis_v2_nar_20260301_20260430.jsonl`
- records: 1,343
- watch labels: 71
- with AI holes: 689
- with danger popular: 462

## primary_label

| label | races |
|---|---:|
| skip | 654 |
| ai_consensus | 290 |
| market_gap | 288 |
| hole_candidate | 111 |

## suggested_use

| suggested_use | races |
|---|---:|
| skip | 636 |
| hole_check | 401 |
| ai_low_rated_popular_check | 288 |
| low_priority | 18 |

## race_type

| race_type | races |
|---|---:|
| nar | 1,343 |

## venue top30

| venue | races |
|---|---:|
| 名古屋 | 195 |
| 園田 | 191 |
| 水沢 | 184 |
| 金沢 | 175 |
| 笠松 | 126 |
| 佐賀 | 125 |
| 高知 | 100 |
| 船橋 | 96 |
| 大井 | 60 |
| 門別 | 43 |
| 帯広 | 25 |
| 姫路 | 23 |

## watch_score上位サンプル

| race | label | use | watch | gap | holes | dangers | summary |
|---|---|---|---:|---:|---:|---:|---|
| 2026-03-13 船橋3R | hole_candidate | hole_check | 95.8 | 100.0 | 4 | 0 | 船橋3R / 診断=hole_candidate / 用途=hole_check / AI穴馬 6番(9人気, 4基支持) / AI中心 6番(4基支持) |
| 2026-03-26 大井9R | hole_candidate | hole_check | 93.4 | 100.0 | 4 | 0 | 大井9R / 診断=hole_candidate / 用途=hole_check / AI穴馬 2番(6人気, 4基支持) / AI中心 2番(4基支持) |
| 2026-04-03 船橋5R | market_gap | ai_low_rated_popular_check | 92.8 | 98.0 | 3 | 2 | 船橋5R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 11番(7人気, 3基支持) / AI低評価人気 8番(2人気, AI支持0基) / AI中心 4番(4基支持) |
| 2026-03-25 名古屋4R | market_gap | ai_low_rated_popular_check | 92.6 | 100.0 | 4 | 2 | 名古屋4R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 5番(9人気, 4基支持) / AI低評価人気 8番(2人気, AI支持0基) / AI中心 5番(4基支持) |
| 2026-04-23 名古屋3R | market_gap | ai_low_rated_popular_check | 92.6 | 100.0 | 4 | 2 | 名古屋3R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 2番(11人気, 4基支持) / AI低評価人気 10番(1人気, AI支持0基) / AI中心 2番(4基支持) |
| 2026-04-10 名古屋4R | market_gap | ai_low_rated_popular_check | 92.3 | 100.0 | 4 | 2 | 名古屋4R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 4番(6人気, 4基支持) / AI低評価人気 11番(1人気, AI支持0基) / AI中心 4番(4基支持) |
| 2026-03-25 名古屋1R | market_gap | ai_low_rated_popular_check | 91.6 | 100.0 | 4 | 2 | 名古屋1R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 1番(7人気, 4基支持) / AI低評価人気 11番(2人気, AI支持0基) / AI中心 1番(4基支持) |
| 2026-03-26 名古屋4R | market_gap | ai_low_rated_popular_check | 91.5 | 100.0 | 4 | 1 | 名古屋4R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 6番(11人気, 4基支持) / AI低評価人気 9番(2人気, AI支持0基) / AI中心 6番(4基支持) |
| 2026-04-08 名古屋4R | market_gap | ai_low_rated_popular_check | 91.5 | 100.0 | 4 | 1 | 名古屋4R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 2番(9人気, 4基支持) / AI低評価人気 9番(1人気, AI支持0基) / AI中心 2番(4基支持) |
| 2026-04-23 名古屋8R | market_gap | ai_low_rated_popular_check | 90.8 | 100.0 | 3 | 3 | 名古屋8R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 6番(11人気, 4基支持) / AI低評価人気 3番(1人気, AI支持0基) / AI中心 6番(4基支持) |
| 2026-04-01 船橋3R | hole_candidate | hole_check | 89.9 | 100.0 | 4 | 0 | 船橋3R / 診断=hole_candidate / 用途=hole_check / AI穴馬 1番(10人気, 3基支持) / AI中心 1番(3基支持) |
| 2026-03-27 名古屋8R | market_gap | ai_low_rated_popular_check | 89.5 | 98.0 | 3 | 2 | 名古屋8R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 3番(10人気, 4基支持) / AI低評価人気 12番(1人気, AI支持0基) / AI中心 3番(4基支持) |
| 2026-03-27 名古屋2R | market_gap | ai_low_rated_popular_check | 89.0 | 100.0 | 4 | 1 | 名古屋2R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 6番(11人気, 4基支持) / AI低評価人気 9番(2人気, AI支持0基) / AI中心 6番(4基支持) |
| 2026-03-11 名古屋5R | market_gap | ai_low_rated_popular_check | 88.5 | 98.0 | 3 | 2 | 名古屋5R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 2番(8人気, 4基支持) / AI低評価人気 8番(1人気, AI支持0基) / AI中心 2番(4基支持) |
| 2026-04-22 名古屋10R | market_gap | ai_low_rated_popular_check | 88.5 | 98.0 | 3 | 2 | 名古屋10R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 2番(11人気, 4基支持) / AI低評価人気 10番(1人気, AI支持0基) / AI中心 2番(4基支持) |
| 2026-03-25 名古屋3R | market_gap | ai_low_rated_popular_check | 87.8 | 98.0 | 3 | 2 | 名古屋3R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 6番(7人気, 3基支持) / AI低評価人気 9番(1人気, AI支持0基) / AI中心 2番(3基支持) |
| 2026-04-20 帯広12R | market_gap | ai_low_rated_popular_check | 87.5 | 100.0 | 3 | 3 | 帯広12R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 3番(5人気, 4基支持) / AI低評価人気 8番(1人気, AI支持0基) / AI中心 3番(4基支持) |
| 2026-03-13 名古屋11R | market_gap | ai_low_rated_popular_check | 87.0 | 98.0 | 3 | 2 | 名古屋11R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 4番(7人気, 4基支持) / AI低評価人気 8番(1人気, AI支持0基) / AI中心 1番(4基支持) |
| 2026-03-25 大井12R | market_gap | ai_low_rated_popular_check | 87.0 | 88.0 | 3 | 1 | 大井12R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 12番(7人気, 4基支持) / AI低評価人気 3番(2人気, AI支持0基) / AI中心 4番(5基支持) |
| 2026-03-13 船橋9R | market_gap | ai_low_rated_popular_check | 86.3 | 88.0 | 3 | 1 | 船橋9R / 診断=market_gap / 用途=ai_low_rated_popular_check / AI穴馬 4番(10人気, 4基支持) / AI低評価人気 10番(2人気, AI支持0基) / AI中心 2番(4基支持) |

