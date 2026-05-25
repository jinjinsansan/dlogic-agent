# 穴党参謀AI 5エンジンtop5ワイド再構築 最終レポート 2026-05-25

## 結論

現時点では、JRA/NARともに「有料配信で購入推奨できるワイド戦略」は採用しない。

理由:

- NLogic込みの現在バックエンドAPI再生成では、JRAもNARも主要ワイド戦略の回収率が安定して100%を超えない。
- JRAは一部の単発戦略でROI 100%超が出たが、最大払戻1件を除外すると大きく崩れる。
- NARは全体的にROI 70%前後以下で、明確に不採用。
- 過去の既存DB版ではJRAワイドが強く見えたが、現在API再生成では再現しない。したがって、旧結果を根拠に配信再開するのは危険。

現サービスとしての推奨:

- 旧火水木単勝配信は継続しない。
- 新ワイド型は、まず「検証中コンテンツ」として出す。
- 購入推奨ではなく、AI注目ペア・観測対象・振り返り前提で運用する。
- 本配信へ戻すには、時刻ベースclean検証と直近フォワード検証が必要。

## 作成した検証資産

調査・監査:

- `docs/anatou_wide_rebirth_research_20260524.md`
- `scripts/wide_rebirth_data_audit.py`
- `docs/wide_rebirth_data_audit_20260525.md`

既存DB版データセット:

- `scripts/build_wide_rebirth_dataset.py`
- `data/wide_rebirth_dataset_20260301_20260525_existing.jsonl`
- `docs/wide_rebirth_dataset_build_20260525.md`
- `docs/wide_rebirth_backtest_20260525.md`

API再生成版:

- `scripts/run_backend_predictions_only.py`
- `scripts/build_wide_rebirth_dataset_from_api.py`
- `scripts/wide_rebirth_backtest.py`
- `data/5eng_races_jra_20260301_20260430.json`
- `data/wide_rebirth_dataset_api_jra_20260301_20260430.jsonl`
- `data/wide_rebirth_dataset_api_nar_20260301_20260430.jsonl`
- `docs/wide_rebirth_backtest_api_jra_20260301_20260430.md`
- `docs/wide_rebirth_backtest_api_nar_20260301_20260430.md`

## データセット概要

### JRA API再生成

- 入力: 564レース
- 出力: 395レース
- NLogicあり: 395レース
- top5あり: 395レース
- wide払戻あり: 395レース
- 使用エンジン: `ilogic`, `viewlogic`, `metalogic`, `nlogic`
- 注意: この再生成では `dlogic` が空になるケースが多く、JRAは実質4エンジン検証。

### NAR API再生成

- 入力: 2,324レース
- 出力: 1,343レース
- NLogicあり: 1,343レース
- top5あり: 1,341レース
- wide払戻あり: 1,343レース
- 4エンジン: 1,187レース
- 5エンジン: 156レース

## JRA結果

対象:

- `data/wide_rebirth_dataset_api_jra_20260301_20260430.jsonl`
- `docs/wide_rebirth_backtest_api_jra_20260301_20260430.md`

主要結果:

| strategy | tickets | ROI | CI5 | drop1 | drop3 | 判断 |
|---|---:|---:|---:|---:|---:|---|
| E1_viewlogic_top2_1pt | 395 | 108.4% | 31.3% | 42.3% | 32.0% | 不採用。1発依存が強すぎる |
| W6_popular_axis_to_ai_holes | 1,555 | 82.4% | 70.5% | 79.7% | 75.3% | 観測候補。黒字ではない |
| E1_nlogic_top2_1pt | 395 | 82.3% | 54.4% | 69.5% | 56.2% | 不採用 |
| W5_vote_axis_to_ai_holes | 1,535 | 76.9% | 63.0% | 72.9% | 68.1% | 不採用 |
| W1_vote_top2_1pt | 395 | 75.7% | 57.9% | 70.1% | 62.0% | 不採用 |
| W2_vote_top3_box3 | 1,185 | 60.4% | 41.7% | 47.6% | 43.1% | 不採用 |
| W4_vote_top5_box10 | 3,950 | 64.6% | 55.3% | 60.8% | 57.2% | 不採用 |

JRAの評価:

- 旧レポートで強かった「合議top3ワイドBOX」は、API再生成ではROI 60.4%まで低下。
- `viewlogic top2` は表面ROI 108.4%だが、最大払戻1件を除くと42.3%。これは商品化できない。
- `popular_axis_to_ai_holes` は月別の崩れが比較的小さいが、ROIが82.4%なので購入推奨には不足。

JRAで残すなら:

- 本配信ではなく「検証中の観測対象」として `W6_popular_axis_to_ai_holes` を見る。
- 目的は配信ではなく、直近フォワードで改善条件を探すこと。

## NAR結果

対象:

- `data/wide_rebirth_dataset_api_nar_20260301_20260430.jsonl`
- `docs/wide_rebirth_backtest_api_nar_20260301_20260430.md`

主要結果:

| strategy | tickets | ROI | CI5 | drop1 | drop3 | 判断 |
|---|---:|---:|---:|---:|---:|---|
| W1_vote_top2_1pt | 1,343 | 71.7% | 49.8% | 62.7% | 53.8% | 不採用 |
| W6_popular_axis_to_ai_holes | 5,312 | 70.6% | 64.4% | 69.6% | 67.9% | 不採用。ただし安定観測候補 |
| E2_ilogic_top3_box3 | 4,029 | 68.3% | 56.4% | 63.9% | 60.3% | 不採用 |
| E1_ilogic_top2_1pt | 1,343 | 64.5% | 47.7% | 59.6% | 51.1% | 不採用 |
| E1_nlogic_top2_1pt | 1,343 | 64.0% | 44.2% | 57.3% | 47.7% | 不採用 |
| W2_vote_top3_box3 | 4,029 | 63.3% | 52.0% | 58.8% | 55.1% | 不採用 |
| W4_vote_top5_box10 | 13,410 | 54.6% | 49.6% | 53.7% | 52.5% | 不採用 |

NARの評価:

- 全体配信は不可。
- top2、top3、top5、NLogic単独、合議、人気軸のいずれも100%に遠い。
- 月別でも3月/4月で大きな改善はなく、地方ワイド全体に優位性は見えない。

NARで残すなら:

- 全場横断ではなく、競馬場別・頭数別・人気帯別・曜日別の探索に限定。
- 現時点で毎日配信や火水木配信へ戻す理由はない。

## 既存DB版とのズレ

既存DB版ではJRAワイドに強い結果が出ていた。

例:

- `E1_dlogic_top2_1pt` JRA ROI 248.3%
- `E2_dlogic_top3_box3` JRA ROI 198.7%
- `W2_vote_top3_box3` JRA ROI 190.2%

しかし、API再生成版ではこの強さが再現していない。

主な理由候補:

- 既存DB版と現在API再生成版でエンジン出力が違う。
- API再生成版では `dlogic` が空になるケースがあり、旧JRA好成績の中心だったdlogicが使えていない。
- 既存DB版には作成時刻・バックフィル・モデル時点の問題が混ざる。
- 当時モデルと現在モデルの差がある。

判断:

- 旧レポートの高ROIは、現行サービスの配信根拠には使わない。
- 今後はAPI再生成版とフォワード検証を基準にする。

## 配信方針

### 今すぐやらないこと

- 「本日の買い目」として購入推奨しない。
- 「回収率200%」など旧数値を訴求しない。
- 火水木の旧単勝ルールを復活しない。
- NAR全場横断のワイド配信をしない。
- top5 BOX10点を主力にしない。

### 可能な暫定コンテンツ

配信するなら、以下のように「検証中」に限定する。

例:

```text
穴党参謀AI 検証ログ
本日はワイド型AIのフォワード検証として、以下のペアを観測対象にします。
購入推奨ではなく、成績集計を目的とした公開検証です。
```

出す候補:

- JRA `W6_popular_axis_to_ai_holes`
- NAR `W6_popular_axis_to_ai_holes`
- ただし、どちらも黒字候補ではなく「比較的崩れにくい観測対象」。

### 本配信に戻す条件

最低条件:

- フォワード検証 n >= 300 tickets
- ROI >= 105%
- CI5 >= 90%
- 最大払戻1件除外後 ROI >= 95%
- 月別または週別で極端な偏りがない
- 最長連敗・最大ドローダウンがサービス説明可能な範囲

推奨条件:

- ROI >= 115%
- CI5 >= 100%
- drop1 >= 100%
- JRA/NARを分けて説明可能

### 停止条件

運用開始後は以下で停止する。

- 直近100 tickets ROI < 70%
- 直近200 tickets ROI < 85%
- 最大ドローダウンが想定上限を超える
- 20レース連続で的中なし
- 週次で検証条件を満たすレースが少なすぎる

## 次にやるべき改善

1. JRAで `dlogic` が空になる原因を直す。
2. JRAをdlogic込み5エンジンで再検証する。
3. NARを競馬場別・人気帯別・頭数別に掘る。
4. `W6_popular_axis_to_ai_holes` をフォワード検証用に日次出力する。
5. Telegram配信は「検証ログ」に変更する。
6. 旧回収率表記を削除し、実績表示はフォワード検証後に限定する。

## 最終判断

穴党参謀AIは、今すぐ「ワイド特化で勝てるサービス」として再開できる状態ではない。

ただし、検証基盤は整った。

- JRA/NARのAPI再生成データセットを作れる。
- NLogic込みtop5の検証ができる。
- ワイド戦略を一括比較できる。
- 採用/不採用の判断軸も整った。

したがって次のフェーズは、配信再開ではなく「フォワード検証型の穴党参謀AI」への移行。

