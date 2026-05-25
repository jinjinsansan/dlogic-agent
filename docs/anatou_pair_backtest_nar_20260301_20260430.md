# 穴党参謀AI ワイドペア条件別バックテスト 2026-05-25

- input: `data\anatou_pair_dataset_nar_20260301_20260430.jsonl`
- pair rows: 63,534
- bootstrap samples: 1000

## 条件サマリ

| condition | races | tickets | hits | hit% | ROI | CI5 | drop1 | drop3 | max | lose_streak | max_dd |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| low_value_popular_pair | 1,280 | 3,323 | 1,072 | 32.3% | 73.3% | 69.9% | 73.0% | 72.5% | 1,010 | 27 | 88,780 |
| popular_axis_ai_hole_strict | 1,085 | 7,194 | 411 | 5.7% | 66.2% | 59.9% | 65.3% | 63.8% | 6,110 | 95 | 243,250 |
| popular_axis_ai_hole | 1,273 | 20,175 | 1,232 | 6.1% | 64.2% | 60.3% | 63.8% | 63.1% | 7,730 | 156 | 721,880 |
| both_ai_supported_top3 | 1,273 | 15,836 | 1,068 | 6.7% | 56.7% | 51.2% | 55.6% | 54.2% | 17,850 | 87 | 687,680 |
| both_ai_supported | 1,273 | 22,573 | 1,537 | 6.8% | 56.1% | 51.8% | 55.3% | 54.1% | 17,850 | 113 | 1,007,330 |
| one_top3_one_hole | 1,273 | 42,375 | 1,507 | 3.6% | 54.7% | 51.2% | 54.1% | 53.2% | 28,540 | 327 | 1,922,180 |
| rank_sum_good | 1,273 | 26,127 | 1,183 | 4.5% | 54.7% | 50.6% | 54.0% | 53.2% | 17,850 | 166 | 1,185,640 |
| multi_engine_mid_hole | 1,273 | 17,047 | 259 | 1.5% | 46.6% | 40.1% | 44.9% | 43.0% | 28,540 | 332 | 927,920 |
| ai_hole_pair | 1,273 | 14,591 | 146 | 1.0% | 42.4% | 34.9% | 40.4% | 38.2% | 28,540 | 582 | 852,320 |

## 月別

| condition | month | tickets | hit% | ROI |
|---|---|---:|---:|---:|
| low_value_popular_pair | 2026-03 | 1,651 | 32.6% | 73.7% |
| low_value_popular_pair | 2026-04 | 1,672 | 31.9% | 73.0% |
| popular_axis_ai_hole_strict | 2026-03 | 3,716 | 5.6% | 66.2% |
| popular_axis_ai_hole_strict | 2026-04 | 3,478 | 5.8% | 66.1% |
| popular_axis_ai_hole | 2026-03 | 10,174 | 5.9% | 65.1% |
| popular_axis_ai_hole | 2026-04 | 10,001 | 6.3% | 63.4% |
| both_ai_supported_top3 | 2026-03 | 8,277 | 7.0% | 56.9% |
| both_ai_supported_top3 | 2026-04 | 7,559 | 6.5% | 56.6% |
| both_ai_supported | 2026-03 | 11,596 | 6.9% | 55.5% |
| both_ai_supported | 2026-04 | 10,977 | 6.8% | 56.8% |
| one_top3_one_hole | 2026-03 | 21,460 | 3.4% | 52.4% |
| one_top3_one_hole | 2026-04 | 20,915 | 3.7% | 57.2% |
| rank_sum_good | 2026-03 | 13,491 | 4.4% | 51.7% |
| rank_sum_good | 2026-04 | 12,636 | 4.7% | 58.0% |
| multi_engine_mid_hole | 2026-03 | 8,698 | 1.4% | 42.5% |
| multi_engine_mid_hole | 2026-04 | 8,349 | 1.6% | 50.9% |
| ai_hole_pair | 2026-03 | 7,567 | 0.9% | 37.9% |
| ai_hole_pair | 2026-04 | 7,024 | 1.1% | 47.2% |

## 競馬場別 top segments

| condition | venue | tickets | hit% | ROI |
|---|---|---:|---:|---:|
| low_value_popular_pair | 門別 | 84 | 36.9% | 96.2% |
| low_value_popular_pair | 水沢 | 451 | 34.6% | 84.0% |
| low_value_popular_pair | 金沢 | 468 | 39.7% | 78.8% |
| low_value_popular_pair | 笠松 | 329 | 35.0% | 77.4% |
| low_value_popular_pair | 佐賀 | 325 | 33.2% | 74.0% |
| low_value_popular_pair | 園田 | 446 | 33.4% | 70.6% |
| low_value_popular_pair | 大井 | 173 | 27.7% | 67.0% |
| low_value_popular_pair | 船橋 | 293 | 24.2% | 66.4% |
| low_value_popular_pair | 高知 | 272 | 27.2% | 66.2% |
| low_value_popular_pair | 名古屋 | 386 | 28.5% | 64.2% |
| popular_axis_ai_hole_strict | 姫路 | 99 | 10.1% | 135.9% |
| popular_axis_ai_hole_strict | 船橋 | 712 | 6.3% | 98.0% |
| popular_axis_ai_hole_strict | 水沢 | 1,083 | 7.1% | 79.1% |
| popular_axis_ai_hole_strict | 園田 | 1,010 | 5.8% | 66.4% |
| popular_axis_ai_hole_strict | 金沢 | 692 | 5.6% | 61.2% |
| popular_axis_ai_hole_strict | 名古屋 | 1,286 | 5.1% | 59.5% |
| popular_axis_ai_hole_strict | 大井 | 412 | 5.1% | 57.7% |
| popular_axis_ai_hole_strict | 佐賀 | 696 | 4.9% | 57.4% |
| popular_axis_ai_hole_strict | 笠松 | 356 | 6.5% | 55.1% |
| popular_axis_ai_hole_strict | 門別 | 206 | 4.4% | 52.5% |
| popular_axis_ai_hole | 船橋 | 1,716 | 5.7% | 74.7% |
| popular_axis_ai_hole | 笠松 | 1,468 | 7.6% | 74.0% |
| popular_axis_ai_hole | 水沢 | 2,794 | 6.5% | 72.2% |
| popular_axis_ai_hole | 高知 | 1,534 | 6.6% | 65.8% |
| popular_axis_ai_hole | 帯広 | 296 | 8.8% | 65.7% |
| popular_axis_ai_hole | 大井 | 1,085 | 5.1% | 65.2% |
| popular_axis_ai_hole | 名古屋 | 3,310 | 5.7% | 64.3% |
| popular_axis_ai_hole | 姫路 | 331 | 5.7% | 62.6% |
| popular_axis_ai_hole | 園田 | 2,928 | 6.2% | 62.3% |
| popular_axis_ai_hole | 門別 | 654 | 6.0% | 58.6% |
| both_ai_supported_top3 | 帯広 | 114 | 8.8% | 100.4% |
| both_ai_supported_top3 | 大井 | 1,263 | 6.3% | 68.2% |
| both_ai_supported_top3 | 船橋 | 1,969 | 5.8% | 66.7% |
| both_ai_supported_top3 | 高知 | 1,105 | 7.6% | 59.3% |
| both_ai_supported_top3 | 園田 | 2,093 | 7.0% | 57.6% |
| both_ai_supported_top3 | 佐賀 | 1,368 | 8.0% | 56.3% |
| both_ai_supported_top3 | 笠松 | 1,310 | 6.8% | 54.5% |
| both_ai_supported_top3 | 名古屋 | 2,219 | 5.3% | 54.1% |
| both_ai_supported_top3 | 金沢 | 1,694 | 8.0% | 53.1% |
| both_ai_supported_top3 | 水沢 | 1,911 | 7.4% | 51.1% |
| both_ai_supported | 帯広 | 280 | 8.6% | 75.1% |
| both_ai_supported | 園田 | 3,086 | 7.5% | 63.3% |
| both_ai_supported | 船橋 | 2,646 | 5.5% | 62.1% |
| both_ai_supported | 大井 | 1,615 | 5.6% | 59.1% |
| both_ai_supported | 名古屋 | 3,131 | 5.6% | 58.9% |
| both_ai_supported | 高知 | 1,618 | 7.8% | 58.5% |
| both_ai_supported | 笠松 | 1,863 | 7.5% | 57.9% |
| both_ai_supported | 水沢 | 2,762 | 7.5% | 51.4% |
| both_ai_supported | 佐賀 | 2,091 | 7.5% | 50.5% |
| both_ai_supported | 金沢 | 2,407 | 7.6% | 49.2% |
| one_top3_one_hole | 帯広 | 484 | 8.1% | 83.9% |
| one_top3_one_hole | 笠松 | 2,830 | 4.9% | 66.8% |
| one_top3_one_hole | 船橋 | 3,886 | 3.4% | 59.0% |
| one_top3_one_hole | 水沢 | 5,743 | 3.5% | 58.3% |
| one_top3_one_hole | 名古屋 | 7,354 | 3.2% | 58.1% |
| one_top3_one_hole | 大井 | 2,459 | 3.2% | 57.2% |
| one_top3_one_hole | 園田 | 6,136 | 3.6% | 56.0% |
| one_top3_one_hole | 高知 | 3,150 | 3.7% | 49.8% |
| one_top3_one_hole | 佐賀 | 4,191 | 3.1% | 46.1% |
| one_top3_one_hole | 金沢 | 4,006 | 3.7% | 45.8% |
| rank_sum_good | 帯広 | 163 | 8.6% | 94.0% |
| rank_sum_good | 笠松 | 1,790 | 5.6% | 66.4% |
| rank_sum_good | 大井 | 1,879 | 3.9% | 60.8% |
| rank_sum_good | 船橋 | 3,112 | 4.2% | 60.6% |
| rank_sum_good | 高知 | 1,890 | 5.2% | 58.0% |
| rank_sum_good | 佐賀 | 2,500 | 4.9% | 55.7% |
| rank_sum_good | 水沢 | 3,357 | 4.8% | 53.0% |
| rank_sum_good | 金沢 | 2,626 | 4.8% | 51.1% |
| rank_sum_good | 名古屋 | 3,994 | 3.8% | 51.1% |
| rank_sum_good | 園田 | 3,586 | 4.3% | 48.6% |
| multi_engine_mid_hole | 帯広 | 156 | 7.1% | 106.3% |
| multi_engine_mid_hole | 笠松 | 1,155 | 2.2% | 57.4% |
| multi_engine_mid_hole | 園田 | 2,371 | 1.8% | 55.7% |
| multi_engine_mid_hole | 大井 | 954 | 1.7% | 54.5% |
| multi_engine_mid_hole | 船橋 | 1,847 | 1.7% | 49.8% |
| multi_engine_mid_hole | 水沢 | 2,260 | 1.1% | 49.6% |
| multi_engine_mid_hole | 名古屋 | 2,895 | 1.4% | 48.6% |
| multi_engine_mid_hole | 高知 | 1,235 | 1.6% | 42.5% |
| multi_engine_mid_hole | 金沢 | 1,707 | 1.1% | 37.4% |
| multi_engine_mid_hole | 佐賀 | 1,619 | 1.5% | 35.5% |
| ai_hole_pair | 帯広 | 101 | 5.9% | 107.7% |
| ai_hole_pair | 大井 | 1,125 | 1.4% | 62.1% |
| ai_hole_pair | 笠松 | 799 | 1.4% | 55.8% |
| ai_hole_pair | 水沢 | 1,817 | 1.0% | 51.3% |
| ai_hole_pair | 名古屋 | 2,580 | 0.9% | 44.6% |
| ai_hole_pair | 園田 | 1,995 | 1.1% | 43.5% |
| ai_hole_pair | 船橋 | 1,736 | 0.9% | 38.0% |
| ai_hole_pair | 高知 | 1,042 | 1.0% | 34.6% |
| ai_hole_pair | 金沢 | 1,295 | 0.7% | 31.9% |
| ai_hole_pair | 佐賀 | 1,386 | 0.9% | 30.0% |

## 判断メモ

- ROIだけで採用しない。CI5、drop1、drop3、月別安定を必ず見る。
- drop1/drop3で崩れる条件は高配当1発依存として扱う。
- Phase 2へ進める候補は、最低でもROI 100%近辺、drop1 90%以上、月別で大崩れしない条件に限定する。

