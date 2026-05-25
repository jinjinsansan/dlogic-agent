# 穴党参謀AI レース診断データセット作成 2026-05-25

- input: `data\wide_rebirth_dataset_api_nar_20260301_20260430.jsonl`
- output: `data\anatou_race_diagnosis_nar_20260301_20260430.jsonl`
- records: 1,343
- watch labels: 1,203
- with AI holes: 1,342
- with danger popular: 759

## primary_label

| label | races |
|---|---:|
| market_gap | 759 |
| hole_candidate | 327 |
| ai_consensus | 257 |

## suggested_use

| suggested_use | races |
|---|---:|
| danger_popular_check | 759 |
| hole_check | 583 |
| skip | 1 |

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
| 2026-04-01 船橋12R | hole_candidate | hole_check | 98.4 | 100.0 | 7 | 0 | 船橋12R / 診断=hole_candidate / 用途=hole_check / AI穴馬 3番(7人気, 4基支持) / AI中心 3番(4基支持) |
| 2026-03-26 大井11R | market_gap | danger_popular_check | 98.1 | 100.0 | 6 | 2 | 大井11R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 6番(11人気, 4基支持) / 危険人気 10番(2人気, AI支持1基) / AI中心 6番(4基支持) |
| 2026-03-31 船橋10R | market_gap | danger_popular_check | 97.4 | 100.0 | 6 | 1 | 船橋10R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 2番(8人気, 4基支持) / 危険人気 5番(2人気, AI支持1基) / AI中心 2番(4基支持) |
| 2026-04-03 船橋8R | market_gap | danger_popular_check | 97.4 | 100.0 | 6 | 1 | 船橋8R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 11番(10人気, 4基支持) / 危険人気 2番(2人気, AI支持1基) / AI中心 11番(4基支持) |
| 2026-03-26 大井1R | market_gap | danger_popular_check | 96.8 | 100.0 | 6 | 1 | 大井1R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 4番(7人気, 3基支持) / 危険人気 8番(3人気, AI支持1基) / AI中心 2番(4基支持) |
| 2026-03-11 船橋5R | market_gap | danger_popular_check | 96.7 | 100.0 | 5 | 2 | 船橋5R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 2番(8人気, 4基支持) / 危険人気 6番(2人気, AI支持1基) / AI中心 2番(4基支持) |
| 2026-03-11 船橋9R | market_gap | danger_popular_check | 96.7 | 100.0 | 5 | 1 | 船橋9R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 3番(7人気, 4基支持) / 危険人気 7番(3人気, AI支持1基) / AI中心 3番(4基支持) |
| 2026-03-30 船橋8R | hole_candidate | hole_check | 96.7 | 100.0 | 6 | 0 | 船橋8R / 診断=hole_candidate / 用途=hole_check / AI穴馬 6番(9人気, 4基支持) / AI中心 6番(4基支持) |
| 2026-04-02 船橋8R | hole_candidate | hole_check | 96.7 | 100.0 | 6 | 0 | 船橋8R / 診断=hole_candidate / 用途=hole_check / AI穴馬 6番(7人気, 3基支持) / AI中心 2番(4基支持) |
| 2026-03-31 船橋11R | market_gap | danger_popular_check | 96.4 | 100.0 | 5 | 1 | 船橋11R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 12番(10人気, 3基支持) / 危険人気 7番(3人気, AI支持1基) / AI中心 13番(4基支持) |
| 2026-04-03 船橋12R | market_gap | danger_popular_check | 96.4 | 100.0 | 5 | 1 | 船橋12R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 3番(9人気, 4基支持) / 危険人気 11番(1人気, AI支持1基) / AI中心 1番(4基支持) |
| 2026-03-11 船橋12R | market_gap | danger_popular_check | 96.1 | 100.0 | 6 | 1 | 船橋12R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 1番(7人気, 4基支持) / 危険人気 12番(2人気, AI支持0基) / AI中心 1番(4基支持) |
| 2026-03-24 大井1R | hole_candidate | hole_check | 96.1 | 100.0 | 6 | 0 | 大井1R / 診断=hole_candidate / 用途=hole_check / AI穴馬 13番(8人気, 3基支持) / AI中心 10番(4基支持) |
| 2026-03-25 大井8R | hole_candidate | hole_check | 96.1 | 100.0 | 6 | 0 | 大井8R / 診断=hole_candidate / 用途=hole_check / AI穴馬 5番(5人気, 3基支持) / AI中心 3番(4基支持) |
| 2026-03-27 大井8R | hole_candidate | hole_check | 96.1 | 100.0 | 6 | 0 | 大井8R / 診断=hole_candidate / 用途=hole_check / AI穴馬 4番(6人気, 4基支持) / AI中心 3番(4基支持) |
| 2026-04-02 船橋3R | market_gap | danger_popular_check | 96.1 | 100.0 | 5 | 1 | 船橋3R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 2番(10人気, 4基支持) / 危険人気 12番(2人気, AI支持0基) / AI中心 5番(4基支持) |
| 2026-04-22 名古屋1R | market_gap | danger_popular_check | 96.1 | 100.0 | 5 | 1 | 名古屋1R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 11番(6人気, 3基支持) / 危険人気 5番(1人気, AI支持0基) / AI中心 9番(4基支持) |
| 2026-03-30 船橋1R | hole_candidate | hole_check | 96.0 | 100.0 | 6 | 0 | 船橋1R / 診断=hole_candidate / 用途=hole_check / AI穴馬 5番(10人気, 4基支持) / AI中心 5番(4基支持) |
| 2026-03-11 船橋1R | market_gap | danger_popular_check | 95.8 | 100.0 | 5 | 1 | 船橋1R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 6番(6人気, 4基支持) / 危険人気 10番(1人気, AI支持1基) / AI中心 6番(4基支持) |
| 2026-03-23 大井9R | market_gap | danger_popular_check | 95.8 | 100.0 | 8 | 1 | 大井9R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 1番(9人気, 4基支持) / 危険人気 11番(2人気, AI支持1基) / AI中心 1番(4基支持) |

