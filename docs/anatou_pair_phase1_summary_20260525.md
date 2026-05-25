# 穴党参謀AI ワイド期待値レイヤー Phase 1 サマリ 2026-05-25

## 実施内容

Phase 1として、レース単位データセットをワイドペア単位に変換し、初期条件別バックテストを実行した。

追加スクリプト:

- `scripts/anatou_pair_dataset.py`
- `scripts/anatou_pair_backtest.py`

生成データ:

- `data/anatou_pair_dataset_jra_20260301_20260430.jsonl`
- `data/anatou_pair_dataset_nar_20260301_20260430.jsonl`

生成レポート:

- `docs/anatou_pair_dataset_build_jra_20260301_20260430.md`
- `docs/anatou_pair_dataset_build_nar_20260301_20260430.md`
- `docs/anatou_pair_backtest_jra_20260301_20260430.md`
- `docs/anatou_pair_backtest_nar_20260301_20260430.md`

## データ件数

### JRA

- races: 395
- pairs: 37,632
- wide hits: 1,187
- all-pair ROI: 52.1%

### NAR

- races: 1,343
- pairs: 63,534
- wide hits: 4,031
- all-pair ROI: 57.5%

## 初期条件の結果

### JRA 全体

| condition | tickets | ROI | CI5 | drop1 | drop3 | 判断 |
|---|---:|---:|---:|---:|---:|---|
| low_value_popular_pair | 1,039 | 79.4% | 71.6% | 77.7% | 75.9% | 人気馬同士。参考用、不採用 |
| popular_axis_ai_hole_strict | 3,384 | 70.3% | 60.0% | 68.3% | 65.4% | 不採用 |
| both_ai_supported_top3 | 4,210 | 70.2% | 58.5% | 66.0% | 59.3% | 不採用 |
| both_ai_supported | 5,801 | 67.8% | 58.3% | 64.7% | 59.9% | 不採用 |
| popular_axis_ai_hole | 7,423 | 67.4% | 59.8% | 66.2% | 64.4% | 不採用 |
| multi_engine_mid_hole | 3,741 | 58.0% | 44.1% | 54.0% | 47.1% | 不採用 |
| ai_hole_pair | 3,751 | 42.3% | 28.0% | 37.5% | 30.5% | 不採用 |

JRA全体では採用候補なし。

### NAR 全体

| condition | tickets | ROI | CI5 | drop1 | drop3 | 判断 |
|---|---:|---:|---:|---:|---:|---|
| low_value_popular_pair | 3,323 | 73.3% | 69.9% | 73.0% | 72.5% | 人気馬同士。参考用、不採用 |
| popular_axis_ai_hole_strict | 7,194 | 66.2% | 59.9% | 65.3% | 63.8% | 不採用 |
| popular_axis_ai_hole | 20,175 | 64.2% | 60.3% | 63.8% | 63.1% | 不採用 |
| both_ai_supported_top3 | 15,836 | 56.7% | 51.2% | 55.6% | 54.2% | 不採用 |
| both_ai_supported | 22,573 | 56.1% | 51.8% | 55.3% | 54.1% | 不採用 |
| multi_engine_mid_hole | 17,047 | 46.6% | 40.1% | 44.9% | 43.0% | 不採用 |
| ai_hole_pair | 14,591 | 42.4% | 34.9% | 40.4% | 38.2% | 不採用 |

NAR全体でも採用候補なし。

## 観測候補

全体では不採用だが、競馬場別に一部観測候補がある。

### JRA

| condition | venue | tickets | ROI | 注意 |
|---|---|---:|---:|---|
| popular_axis_ai_hole_strict | 福島 | 330 | 93.5% | 黒字未満。観測のみ |
| both_ai_supported_top3 | 中山 | 1,387 | 92.5% | 黒字未満。比較的マシ |
| rank_sum_good | 中山 | 2,521 | 89.6% | 黒字未満。観測のみ |
| both_ai_supported | 中山 | 1,941 | 85.5% | 黒字未満 |
| popular_axis_ai_hole | 福島 | 863 | 85.9% | 黒字未満 |

JRAは「中山」「福島」にやや残り目があるが、現時点では本配信不可。

### NAR

| condition | venue | tickets | ROI | 注意 |
|---|---|---:|---:|---|
| popular_axis_ai_hole_strict | 姫路 | 99 | 135.9% | 件数不足。要追加期間 |
| both_ai_supported_top3 | 帯広 | 114 | 100.4% | 件数不足。ギリギリ |
| multi_engine_mid_hole | 帯広 | 156 | 106.3% | 件数不足。要注意 |
| ai_hole_pair | 帯広 | 101 | 107.7% | 件数不足。高リスク |
| low_value_popular_pair | 門別 | 84 | 96.2% | 件数不足、人気寄り |
| popular_axis_ai_hole_strict | 船橋 | 712 | 98.0% | 黒字未満だが件数あり |

NARは「帯広」「姫路」「船橋」に観測候補があるが、全体配信は不可。

## 重要な判断

1. Phase 1時点で、購入推奨へ進める条件はない。
2. 既存エンジンtop5を特徴量化しても、初期ルールだけでは黒字化しない。
3. ただし、競馬場別に観測継続できる条件はある。
4. Phase 2でいきなりTelegram本配信へ進むのは早い。
5. 次は条件探索をもう一段深くする必要がある。

## Phase 1 追加でやるべき深掘り

Phase 2に行く前に、以下を追加する。

- 競馬場別条件を自動探索する。
- 人気帯をさらに細かく切る。
- 頭数別に切る。
- engine別の組み合わせを見る。
- NLogic支持あり/なしで分ける。
- dlogicが出るNARレースだけ分ける。
- 高配当1発依存を除いた安定条件を優先する。

追加候補スクリプト:

- `scripts/anatou_pair_search.py`

目的:

```text
条件を人間が手で数個試すのではなく、
venue / race_type / popularity / votes / rank / field_size を組み合わせて
安定条件候補を自動探索する。
```

## Phase 2へ進む条件

以下のいずれかを満たす条件が出たら、シグナル生成へ進む。

- tickets >= 300
- ROI >= 100%
- drop1 >= 90%
- drop3 >= 85%
- 月別で大崩れしない

理想:

- ROI >= 110%
- CI5 >= 90%
- drop1 >= 100%

## 現時点の結論

穴党参謀AIの方向性は正しい。

ただし、Phase 1の初期ルールではまだ弱い。

次は `anatou_pair_search.py` で、競馬場・人気帯・支持数・頭数を組み合わせた探索を行う。

