# 穴党参謀AI ワイドペア条件別バックテスト 2026-05-25

- input: `data\anatou_pair_dataset_jra_20260301_20260430.jsonl`
- pair rows: 37,632
- bootstrap samples: 1000

## 条件サマリ

| condition | races | tickets | hits | hit% | ROI | CI5 | drop1 | drop3 | max | lose_streak | max_dd |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| low_value_popular_pair | 389 | 1,039 | 270 | 26.0% | 79.4% | 71.6% | 77.7% | 75.9% | 1,680 | 17 | 21,890 |
| popular_axis_ai_hole_strict | 372 | 3,384 | 175 | 5.2% | 70.3% | 60.0% | 68.3% | 65.4% | 6,690 | 107 | 120,790 |
| both_ai_supported_top3 | 385 | 4,210 | 360 | 8.6% | 70.2% | 58.5% | 66.0% | 59.3% | 17,790 | 80 | 154,220 |
| rank_sum_good | 385 | 7,521 | 360 | 4.8% | 68.2% | 58.3% | 64.8% | 60.4% | 26,130 | 129 | 266,830 |
| both_ai_supported | 385 | 5,801 | 473 | 8.2% | 67.8% | 58.3% | 64.7% | 59.9% | 17,790 | 83 | 214,060 |
| popular_axis_ai_hole | 385 | 7,423 | 389 | 5.2% | 67.4% | 59.8% | 66.2% | 64.4% | 8,760 | 170 | 243,050 |
| one_top3_one_hole | 385 | 14,448 | 520 | 3.6% | 61.8% | 55.5% | 60.7% | 58.9% | 15,120 | 265 | 559,800 |
| multi_engine_mid_hole | 382 | 3,741 | 85 | 2.3% | 58.0% | 44.1% | 54.0% | 47.1% | 15,120 | 261 | 164,630 |
| ai_hole_pair | 385 | 3,751 | 39 | 1.0% | 42.3% | 28.0% | 37.5% | 30.5% | 18,100 | 515 | 216,250 |

## 月別

| condition | month | tickets | hit% | ROI |
|---|---|---:|---:|---:|
| low_value_popular_pair | 2026-03 | 558 | 25.3% | 78.2% |
| low_value_popular_pair | 2026-04 | 481 | 26.8% | 80.8% |
| popular_axis_ai_hole_strict | 2026-03 | 1,791 | 5.1% | 63.6% |
| popular_axis_ai_hole_strict | 2026-04 | 1,593 | 5.3% | 77.8% |
| both_ai_supported_top3 | 2026-03 | 2,173 | 8.7% | 72.8% |
| both_ai_supported_top3 | 2026-04 | 2,037 | 8.4% | 67.5% |
| rank_sum_good | 2026-03 | 3,729 | 4.6% | 69.0% |
| rank_sum_good | 2026-04 | 3,792 | 4.9% | 67.5% |
| both_ai_supported | 2026-03 | 3,005 | 8.4% | 67.6% |
| both_ai_supported | 2026-04 | 2,796 | 7.9% | 68.1% |
| popular_axis_ai_hole | 2026-03 | 3,872 | 5.2% | 65.8% |
| popular_axis_ai_hole | 2026-04 | 3,551 | 5.3% | 69.2% |
| one_top3_one_hole | 2026-03 | 7,388 | 3.7% | 60.6% |
| one_top3_one_hole | 2026-04 | 7,060 | 3.5% | 62.9% |
| multi_engine_mid_hole | 2026-03 | 1,879 | 2.3% | 48.8% |
| multi_engine_mid_hole | 2026-04 | 1,862 | 2.3% | 67.4% |
| ai_hole_pair | 2026-03 | 1,870 | 0.9% | 31.6% |
| ai_hole_pair | 2026-04 | 1,881 | 1.2% | 53.0% |

## 競馬場別 top segments

| condition | venue | tickets | hit% | ROI |
|---|---|---:|---:|---:|
| low_value_popular_pair | 中山 | 347 | 27.4% | 80.8% |
| low_value_popular_pair | 福島 | 113 | 21.2% | 79.6% |
| low_value_popular_pair | 阪神 | 389 | 28.5% | 79.4% |
| low_value_popular_pair | 中京 | 190 | 21.1% | 76.5% |
| popular_axis_ai_hole_strict | 福島 | 330 | 4.5% | 93.5% |
| popular_axis_ai_hole_strict | 中山 | 1,219 | 5.3% | 73.2% |
| popular_axis_ai_hole_strict | 阪神 | 1,245 | 5.5% | 65.3% |
| popular_axis_ai_hole_strict | 中京 | 590 | 4.7% | 61.7% |
| both_ai_supported_top3 | 中山 | 1,387 | 9.2% | 92.5% |
| both_ai_supported_top3 | 中京 | 778 | 7.7% | 67.5% |
| both_ai_supported_top3 | 福島 | 491 | 5.5% | 61.8% |
| both_ai_supported_top3 | 阪神 | 1,554 | 9.3% | 54.4% |
| rank_sum_good | 中山 | 2,521 | 5.3% | 89.6% |
| rank_sum_good | 阪神 | 2,514 | 4.9% | 63.7% |
| rank_sum_good | 中京 | 1,430 | 4.3% | 52.3% |
| rank_sum_good | 福島 | 1,056 | 3.9% | 49.6% |
| both_ai_supported | 中山 | 1,941 | 9.0% | 85.5% |
| both_ai_supported | 中京 | 1,117 | 7.3% | 67.5% |
| both_ai_supported | 福島 | 711 | 5.8% | 67.3% |
| both_ai_supported | 阪神 | 2,032 | 8.7% | 51.3% |
| popular_axis_ai_hole | 福島 | 863 | 6.1% | 85.9% |
| popular_axis_ai_hole | 阪神 | 2,659 | 5.0% | 67.6% |
| popular_axis_ai_hole | 中山 | 2,529 | 5.1% | 64.0% |
| popular_axis_ai_hole | 中京 | 1,372 | 5.2% | 61.6% |
| one_top3_one_hole | 中山 | 4,877 | 3.7% | 66.3% |
| one_top3_one_hole | 阪神 | 5,109 | 3.6% | 61.9% |
| one_top3_one_hole | 福島 | 1,783 | 3.5% | 59.1% |
| one_top3_one_hole | 中京 | 2,679 | 3.5% | 55.0% |
| multi_engine_mid_hole | 中山 | 1,248 | 2.1% | 65.7% |
| multi_engine_mid_hole | 中京 | 672 | 2.8% | 58.1% |
| multi_engine_mid_hole | 阪神 | 1,336 | 2.2% | 55.0% |
| multi_engine_mid_hole | 福島 | 485 | 2.1% | 46.6% |
| ai_hole_pair | 中山 | 1,236 | 1.3% | 64.6% |
| ai_hole_pair | 阪神 | 1,198 | 0.9% | 36.0% |
| ai_hole_pair | 中京 | 752 | 0.9% | 28.3% |
| ai_hole_pair | 福島 | 565 | 0.9% | 26.0% |

## 判断メモ

- ROIだけで採用しない。CI5、drop1、drop3、月別安定を必ず見る。
- drop1/drop3で崩れる条件は高配当1発依存として扱う。
- Phase 2へ進める候補は、最低でもROI 100%近辺、drop1 90%以上、月別で大崩れしない条件に限定する。

