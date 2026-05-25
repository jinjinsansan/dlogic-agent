# 穴党参謀AI レース診断AI 初回検証サマリ 2026-05-25

## 目的

穴党参謀AIを、単純な買い目推奨ではなく「ユーザーがレースを判断しやすくなる診断AI」に作り替えるため、既存バックエンドエンジンの出力を使って以下を検証した。

- 今日見るべきレースを選べるか
- AI穴馬候補を出せるか
- AI低評価の人気馬を検出できるか
- 荒れやすいレースを診断できるか

既存のnetkeita向けエンジンやAPI本体は変更しない。今回追加したのは、穴党参謀AI用の診断レイヤーと検証スクリプトのみ。

## 今回追加したファイル

### 診断生成

- `scripts/anatou_race_diagnosis.py`

入力のレース別エンジン出力JSONLから、レース診断JSONLと集計レポートを生成する。

主な出力項目:

- `watch_score`
- `primary_label`
- `labels`
- `suggested_use`
- `ai_hole_horses`
- `danger_popular_horses`
- `consensus_horses`
- `summary_text`

### 診断バックテスト

- `scripts/anatou_race_diagnosis_backtest.py`

診断結果とレース結果を突き合わせ、回収率ではなく「診断ラベルが説明力を持つか」を検証する。

主な検証指標:

- `hole_top3_rate`: AI穴馬候補が3着内相当に入った割合
- `danger_miss_rate`: 危険人気馬候補が3着内相当を外した割合
- `avg_max_wide`: そのレースで最大のワイド配当
- `high_wide_rate`: 高配当ワイドが出た割合
- `super_high_wide_rate`: 超高配当ワイドが出た割合

結果データ上に確定着順top3がないケースがあるため、今回はワイド的中組み合わせに含まれる馬を「3着内相当」として推定した。

## 生成済みデータ

### JRA

- 入力: `data/wide_rebirth_dataset_api_jra_20260301_20260430.jsonl`
- 診断: `data/anatou_race_diagnosis_jra_20260301_20260430.jsonl`
- 生成レポート: `docs/anatou_race_diagnosis_build_jra_20260301_20260430.md`
- 検証レポート: `docs/anatou_race_diagnosis_backtest_jra_20260301_20260430.md`

件数:

- 診断対象: 395レース
- watchラベルあり: 298レース
- AI穴馬あり: 394レース
- 危険人気馬あり: 159レース

### NAR

- 入力: `data/wide_rebirth_dataset_api_nar_20260301_20260430.jsonl`
- 診断: `data/anatou_race_diagnosis_nar_20260301_20260430.jsonl`
- 生成レポート: `docs/anatou_race_diagnosis_build_nar_20260301_20260430.md`
- 検証レポート: `docs/anatou_race_diagnosis_backtest_nar_20260301_20260430.md`

件数:

- 診断対象: 1,343レース
- watchラベルあり: 1,203レース
- AI穴馬あり: 1,342レース
- 危険人気馬あり: 759レース

## 初回検証結果

### JRA

primary label別の主な結果:

| label | races | hole_top3 | danger_miss | avg_max_wide | high_wide | super_high_wide |
|---|---:|---:|---:|---:|---:|---:|
| market_gap | 159 | 15.3% | 55.0% | 3231 | 75.5% | 28.9% |
| hole_candidate | 97 | 14.5% | - | 3051 | 66.0% | 23.7% |
| ai_consensus | 139 | 19.1% | - | 2225 | 48.2% | 17.3% |

watch score別:

| bucket | races | hole_top3 | danger_miss | avg_max_wide | high_wide | super_high_wide |
|---|---:|---:|---:|---:|---:|---:|
| watch_80 | 89 | 16.0% | 55.0% | 3351 | 73.0% | 31.5% |
| watch_70 | 112 | 14.6% | 55.0% | 3147 | 73.2% | 25.9% |
| watch_60 | 97 | 14.2% | - | 3148 | 67.0% | 24.7% |
| watch_lt60 | 97 | 18.5% | - | 1597 | 39.2% | 12.4% |

読み取り:

- `market_gap` と `watch_80` は、荒れたレース・高配当ワイドが出たレースを拾う力がある。
- `watch_lt60` は平均最大ワイドと高配当率が明確に低く、見送り判定の材料に使える可能性がある。
- `danger_popular_horses` はJRAでも `danger_miss_rate` が55.0%で、まだ「危険人気馬」と断言するには弱い。

### NAR

primary label別の主な結果:

| label | races | hole_top3 | danger_miss | avg_max_wide | high_wide | super_high_wide |
|---|---:|---:|---:|---:|---:|---:|
| market_gap | 759 | 13.2% | 40.6% | 1703 | 54.4% | 19.1% |
| hole_candidate | 327 | 14.5% | - | 1597 | 54.1% | 18.3% |
| ai_consensus | 257 | 14.7% | - | 1137 | 37.4% | 13.6% |

watch score別:

| bucket | races | hole_top3 | danger_miss | avg_max_wide | high_wide | super_high_wide |
|---|---:|---:|---:|---:|---:|---:|
| watch_80 | 602 | 13.1% | 40.8% | 1820 | 57.8% | 20.1% |
| watch_70 | 452 | 13.2% | 40.2% | 1600 | 51.5% | 18.4% |
| watch_60 | 149 | 16.3% | 42.6% | 1296 | 49.0% | 15.4% |
| watch_lt60 | 140 | 14.9% | - | 880 | 27.9% | 12.9% |

会場別で目立つ候補:

| venue | races | high_wide | avg_max_wide | note |
|---|---:|---:|---:|---|
| 大井 | 60 | 70.0% | 2184 | 高配当検出の候補 |
| 帯広 | 25 | 68.0% | 1603 | 件数は少ないが穴馬的中率も高め |
| 船橋 | 48 | 60.4% | 2449 | 高配当検出の候補 |
| 名古屋 | 245 | 60.0% | 1645 | 件数が多く検証価値あり |

読み取り:

- NARでも `watch_80` は `watch_lt60` より高配当レースを明確に拾っている。
- ただし `danger_popular_horses` はNARでは弱い。`danger_miss_rate` が40.6%で、人気馬を危険扱いする根拠としては不足。
- 大井、船橋、名古屋、帯広は次の深掘り候補。

## 現時点で使える可能性があるもの

### 1. 荒れそうなレース診断

`watch_score`、`market_gap`、`hole_candidate` は、少なくとも「高配当が出やすいレースを見つける」方向では有望。

特にJRAでは `market_gap` の `high_wide_rate` が75.5%、`watch_80` が73.0%で、`watch_lt60` の39.2%と差がある。

NARでも `watch_80` が57.8%、`watch_lt60` が27.9%で差がある。

### 2. 見送り診断

`watch_lt60` はJRA/NARともに平均最大ワイドと高配当率が低い。

今後は「買うべきレース」よりも先に、「見る価値が薄いレースを除外する」機能として磨く価値がある。

### 3. 会場別診断

NARは会場差が大きい。全地方競馬を同一ロジックで扱うより、会場別に診断の重みを変える方がよい。

## 現時点で使うべきではないもの

### 1. 危険人気馬という断定表現

現行ロジックの `danger_popular_horses` は弱い。

- JRA: danger miss 55.0%
- NAR: danger miss 40.6%

特にNARでは、AIが低評価した人気馬でも3着内相当に残るケースが多い。現段階で「危険人気馬」としてユーザーに強く出すと、信頼を落とす可能性がある。

当面は表現を弱める。

- NG: 危険人気馬
- OK: AI低評価の人気馬
- OK: AI評価が割れた人気馬
- OK: 過信注意の人気馬

### 2. AI穴馬の広すぎる抽出

初回ロジックでは、ほぼ全レースにAI穴馬が出ている。

- JRA: 394/395レース
- NAR: 1,342/1,343レース

これはサービスとして使いにくい。穴馬候補は「毎レース出るもの」ではなく、「出たら注目するもの」に絞る必要がある。

### 3. 現行skip判定

skipが少なすぎる。

- JRA: 1レース
- NAR: 1レース

診断AIとしては、見送り判断が重要な価値になるため、skip/low priorityをもっと出せるようにする。

## 次にやるべき開発

次はPhase 3の配信生成へ進まず、診断ロジックv2で絞り込みを行う。

### v2調整方針

#### AI穴馬

現行:

- 人気5番手以下
- top5_votes 2以上

v2候補:

- 人気5番手以下
- top5_votes 3以上、または top3_votes 2以上
- 14番人気以下は初期除外、または別枠の大穴として扱う
- AI支持が高くても人気が極端に低すぎる馬は「ロマン枠」として別表示

#### AI低評価人気馬

現行:

- 人気3番手以内
- top5_votes 1以下
- top3_votes 0

v2候補:

- 人気3番手以内
- top5_votes 0、または top3_votes 0かつ全体支持が低い
- ただし検証上は断定せず、表現は「AI低評価人気馬」にする
- JRA/NARで閾値を分ける

#### watch/skip

v2候補:

- watch: `watch_score >= 80`
- normal: `60 <= watch_score < 80`
- low_priority: `watch_score < 60`
- skip: `watch_score < 60` かつ 強いAI穴馬なし かつ 強いmarket gapなし

#### NAR会場別

まず以下を個別候補として扱う。

- 大井
- 船橋
- 名古屋
- 帯広

その他会場はサンプル数と成績を見て後から追加する。

## フェーズ判断

現時点でTelegram配信や有料サービスに進むのは早い。

ただし、方向性は悪くない。

買い目推奨ではなく、以下のような診断コンテンツとして磨くべき。

- 今日見るべきレース
- 荒れ警戒レース
- AI穴馬候補
- AI低評価人気馬
- 見送り候補レース
- 会場別の狙いどころ

次の作業は、診断ロジックv2を実装し、JRA/NARで再検証すること。

## v2実装後の再検証

`scripts/anatou_race_diagnosis.py` に `--profile v2` を追加し、以下の調整を入れた。

- AI穴馬を「人気5-12番手、AI top5支持3基以上、人気とAI平均順位の差3.0以上、かつtop3支持2基以上または本命支持1基以上」に変更
- 「危険人気馬」という表示をやめ、summary上は「AI低評価人気」に変更
- watch閾値を上げ、`low_priority` と `skip` を出しやすくした

### v2生成ファイル

- `data/anatou_race_diagnosis_v2_jra_20260301_20260430.jsonl`
- `data/anatou_race_diagnosis_v2_nar_20260301_20260430.jsonl`
- `docs/anatou_race_diagnosis_build_v2_jra_20260301_20260430.md`
- `docs/anatou_race_diagnosis_build_v2_nar_20260301_20260430.md`
- `docs/anatou_race_diagnosis_backtest_v2_jra_20260301_20260430.md`
- `docs/anatou_race_diagnosis_backtest_v2_nar_20260301_20260430.md`

### JRA v2

| label | races | hole_top3 | danger_miss | avg_max_wide | high_wide | super_high |
|---|---:|---:|---:|---:|---:|---:|
| market_gap | 60 | 17.1% | 54.5% | 2965 | 71.7% | 26.7% |
| hole_candidate | 31 | 11.9% | - | 3276 | 64.5% | 29.0% |
| ai_consensus | 139 | 13.9% | - | 2876 | 64.7% | 28.1% |
| skip | 165 | - | 63.3% | 2665 | 59.4% | 21.8% |

JRAは初回よりも候補数が絞れた。

- AI穴馬あり: 394レースから230レースへ減少
- watch labels: 298レースから6レースへ減少
- skip: 1レースから165レースへ増加

ただし、skipの `high_wide_rate` が59.4%あり、まだ「完全見送り」と断定するには弱い。JRAは全体的に高配当ワイドが多い期間だった可能性もあるため、skipは「低優先度」寄りの扱いがよい。

### NAR v2

| label | races | hole_top3 | danger_miss | avg_max_wide | high_wide | super_high |
|---|---:|---:|---:|---:|---:|---:|
| market_gap | 427 | 12.2% | 42.4% | 1846 | 57.6% | 20.1% |
| hole_candidate | 225 | 11.9% | - | 1539 | 50.2% | 18.7% |
| ai_consensus | 505 | 14.5% | - | 1409 | 48.5% | 13.3% |
| skip | 186 | - | 30.8% | 1401 | 44.1% | 12.9% |

NARも初回よりは絞れた。

- AI穴馬あり: 1,342レースから1,157レースへ減少
- watch labels: 1,203レースから185レースへ減少
- skip: 1レースから186レースへ増加

ただし、AI穴馬はまだ多すぎる。NARは会場差が大きいため、全会場共通ロジックだけでは不十分。

### v2時点の判断

JRAは診断AIとして次の試作に進める水準に近づいた。

NARは大井、船橋、名古屋、帯広などの会場別ロジックが必要。特に帯広は件数が25と少ないが `hole_top3` が28.2%、`danger_miss` が61.5%で、他会場とは別扱いにする価値がある。

次の実装候補:

1. JRA/NAR共通の今日用診断フォーマッタを作る
2. NARの会場別閾値テーブルを追加する
3. 「skip」表現は避け、最初は「低優先度」として出す
4. Telegram配信前に、1日分の診断プレビューをMarkdown/JSONで出力する

## NAR会場別調整後のv2

`scripts/anatou_race_diagnosis.py` にNAR会場別ルールを追加した。

方針:

- JRAは既存v2のまま維持
- NAR全体は厳しめにする
- 大井、船橋、名古屋、帯広だけ注目会場として拾いやすくする
- その他会場はAI穴馬の条件を厳しくし、候補乱発を防ぐ

NAR会場別ルール:

| group | min_pop | max_pop | min_top5 | min_gap | market_gap_threshold | watch_threshold |
|---|---:|---:|---:|---:|---:|---:|
| 大井/船橋/名古屋 | 5 | 12 | 3 | 3.0 | 55 | 70 |
| 帯広 | 5 | 12 | 3 | 2.5 | 55 | 70 |
| その他NAR | 5 | 11 | 4 | 4.0 | 70 | 75 |

### NAR会場別調整後の件数

| item | before | after |
|---|---:|---:|
| records | 1,343 | 1,343 |
| watch labels | 185 | 71 |
| with AI holes | 1,157 | 689 |
| with AI low-rated popular | 462 | 462 |
| skip | 186 | 654 |

候補数は大きく絞れた。特にAI穴馬が689レースまで減り、低優先度/skipが増えた。

### NAR会場別調整後の検証

| label | races | hole_top3 | danger_miss | avg_max_wide | high_wide | super_high |
|---|---:|---:|---:|---:|---:|---:|
| hole_candidate | 111 | 11.3% | - | 1935 | 62.2% | 26.1% |
| market_gap | 288 | 12.4% | 45.5% | 2024 | 61.5% | 22.6% |
| ai_consensus | 290 | 12.2% | - | 1487 | 47.9% | 15.2% |
| skip | 654 | - | 34.4% | 1342 | 46.0% | 12.4% |

改善点:

- `hole_candidate` と `market_gap` が `skip` より高配当率で明確に上回った
- `super_high` も `skip` より高い
- 地方の全レースに近い数へ穴馬を出す状態は改善した

残る課題:

- NARの `AI低評価人気` はまだ弱い。`danger_miss` は45.5%で、強い消し材料ではない
- `skip` でも `high_wide` が46.0%あるため、表現は「見送り」より「低優先度」が妥当
- 帯広は `hole_top3` 27.3%、`danger_miss` 61.5%と目立つが、25レースしかないため追加期間で検証が必要

### 会場別の現状

| venue | races | hole_top3 | danger_miss | high_wide | avg_watch |
|---|---:|---:|---:|---:|---:|
| 大井 | 60 | 14.1% | 44.4% | 70.0% | 51.0 |
| 帯広 | 25 | 27.3% | 61.5% | 68.0% | 56.8 |
| 船橋 | 96 | 16.2% | 30.8% | 60.4% | 60.1 |
| 名古屋 | 195 | 10.4% | 46.1% | 60.0% | 57.1 |
| 水沢 | 184 | 16.7% | 45.7% | 53.3% | 34.1 |
| 園田 | 191 | 5.3% | 40.2% | 51.8% | 35.5 |

地方は次の扱いがよい。

- 大井、船橋、名古屋、帯広: 通常診断対象
- 水沢: 穴馬だけ追加検証
- 園田、金沢、姫路、門別: 現時点では慎重

### 次の実装判断

会場別調整後、NARも「全レースに穴を出す」状態からは脱した。

次は今日用の診断プレビュー生成へ進める。配信文では以下の表現にする。

- `skip` は画面・内部では使ってよいが、ユーザー表示は「低優先度」
- `danger_popular` は使わず「AI低評価人気」
- 買い目推奨ではなく「見るべきレース」「荒れ警戒」「AI穴馬」「過信注意」の診断にする
