# 穴党参謀AI レース診断データセット作成 2026-05-25

- input: `data\wide_rebirth_dataset_api_jra_20260301_20260430.jsonl`
- output: `data\anatou_race_diagnosis_jra_20260301_20260430.jsonl`
- records: 395
- watch labels: 298
- with AI holes: 394
- with danger popular: 159

## primary_label

| label | races |
|---|---:|
| market_gap | 159 |
| ai_consensus | 139 |
| hole_candidate | 97 |

## suggested_use

| suggested_use | races |
|---|---:|
| hole_check | 235 |
| danger_popular_check | 159 |
| skip | 1 |

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
| 2026-04-12 阪神8R | market_gap | danger_popular_check | 93.7 | 100.0 | 4 | 2 | 阪神8R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 2番(5人気, 3基支持) / 危険人気 10番(2人気, AI支持1基) / AI中心 8番(4基支持) |
| 2026-03-15 中京7R | market_gap | danger_popular_check | 92.8 | 100.0 | 5 | 1 | 中京7R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 2番(10人気, 3基支持) / 危険人気 1番(1人気, AI支持0基) / AI中心 15番(4基支持) |
| 2026-04-12 福島4R | market_gap | danger_popular_check | 92.8 | 100.0 | 6 | 2 | 福島4R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 1番(6人気, 4基支持) / 危険人気 16番(1人気, AI支持1基) / AI中心 1番(4基支持) |
| 2026-04-12 阪神1R | market_gap | danger_popular_check | 92.8 | 100.0 | 5 | 2 | 阪神1R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 3番(6人気, 4基支持) / 危険人気 5番(2人気, AI支持1基) / AI中心 3番(4基支持) |
| 2026-04-19 福島5R | market_gap | danger_popular_check | 92.8 | 100.0 | 5 | 2 | 福島5R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 7番(5人気, 3基支持) / 危険人気 16番(1人気, AI支持1基) / AI中心 2番(3基支持) |
| 2026-03-22 中山4R | market_gap | danger_popular_check | 92.5 | 100.0 | 6 | 2 | 中山4R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 3番(14人気, 3基支持) / 危険人気 8番(2人気, AI支持1基) / AI中心 7番(3基支持) |
| 2026-03-28 中山10R | market_gap | danger_popular_check | 92.4 | 100.0 | 4 | 2 | 中山10R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 10番(5人気, 4基支持) / 危険人気 5番(1人気, AI支持1基) / AI中心 10番(4基支持) |
| 2026-04-19 福島6R | market_gap | danger_popular_check | 92.4 | 100.0 | 5 | 2 | 福島6R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 3番(10人気, 3基支持) / 危険人気 8番(1人気, AI支持1基) / AI中心 5番(4基支持) |
| 2026-03-21 中京7R | market_gap | danger_popular_check | 92.1 | 100.0 | 6 | 3 | 中京7R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 3番(11人気, 4基支持) / 危険人気 5番(1人気, AI支持1基) / AI中心 3番(4基支持) |
| 2026-04-11 福島2R | market_gap | danger_popular_check | 91.7 | 100.0 | 5 | 1 | 福島2R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 3番(9人気, 3基支持) / 危険人気 10番(3人気, AI支持1基) / AI中心 3番(3基支持) |
| 2026-04-19 中山11R | market_gap | danger_popular_check | 91.7 | 100.0 | 5 | 1 | 中山11R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 11番(8人気, 3基支持) / 危険人気 12番(2人気, AI支持0基) / AI中心 11番(3基支持) |
| 2026-04-05 阪神1R | market_gap | danger_popular_check | 91.4 | 100.0 | 5 | 2 | 阪神1R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 3番(8人気, 4基支持) / 危険人気 8番(1人気, AI支持0基) / AI中心 13番(4基支持) |
| 2026-04-04 中山9R | market_gap | danger_popular_check | 90.5 | 100.0 | 4 | 2 | 中山9R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 1番(5人気, 3基支持) / 危険人気 13番(1人気, AI支持1基) / AI中心 4番(4基支持) |
| 2026-04-18 福島8R | market_gap | danger_popular_check | 90.5 | 100.0 | 5 | 2 | 福島8R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 7番(5人気, 3基支持) / 危険人気 8番(1人気, AI支持1基) / AI中心 2番(4基支持) |
| 2026-03-29 阪神9R | market_gap | danger_popular_check | 90.1 | 100.0 | 6 | 3 | 阪神9R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 7番(8人気, 4基支持) / 危険人気 1番(1人気, AI支持0基) / AI中心 7番(4基支持) |
| 2026-04-19 福島8R | market_gap | danger_popular_check | 90.1 | 100.0 | 5 | 2 | 福島8R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 5番(5人気, 4基支持) / 危険人気 6番(1人気, AI支持1基) / AI中心 5番(4基支持) |
| 2026-03-29 阪神3R | market_gap | danger_popular_check | 90.0 | 100.0 | 6 | 2 | 阪神3R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 1番(9人気, 3基支持) / 危険人気 3番(1人気, AI支持0基) / AI中心 1番(3基支持) |
| 2026-04-05 阪神3R | market_gap | danger_popular_check | 90.0 | 100.0 | 4 | 2 | 阪神3R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 6番(6人気, 3基支持) / 危険人気 7番(2人気, AI支持1基) / AI中心 6番(3基支持) |
| 2026-03-14 中京4R | market_gap | danger_popular_check | 89.4 | 100.0 | 5 | 1 | 中京4R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 16番(7人気, 3基支持) / 危険人気 5番(2人気, AI支持0基) / AI中心 16番(3基支持) |
| 2026-04-11 福島3R | market_gap | danger_popular_check | 89.4 | 100.0 | 4 | 2 | 福島3R / 診断=market_gap / 用途=danger_popular_check / AI穴馬 1番(8人気, 3基支持) / 危険人気 11番(2人気, AI支持0基) / AI中心 1番(3基支持) |

