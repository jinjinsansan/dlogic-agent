# 穴党参謀AI レース診断AI 開発計画 2026-05-25

## 目的

穴党参謀AIを「買い目を出すAI」から、「競馬ファンの判断を助けるレース診断AI」へ作り直す。

既存のnetkeita向けバックエンドエンジンは変更しない。穴党参謀AIは既存エンジンの top5 を読み取り、レース単位で以下を診断する。

- 今日見るべきレース
- 危険人気馬
- AI穴馬
- AI一致レース
- AI意見割れレース
- 荒れ警戒レース
- 堅実寄りレース
- 見送りレース
- 参考買い目を出すならどの方向か

## 方針転換

旧計画:

```text
ワイドペア期待値レイヤーを主軸にし、買い目候補を探す
```

新計画:

```text
レース診断AIを主軸にし、ユーザーの予想判断を助ける
```

ワイドペア期待値レイヤーは破棄しない。以下の補助機能として使う。

- AI穴馬の根拠
- 参考ワイド候補
- 人気軸 × AI穴馬の過去傾向
- 見送り判定の補助

主役は買い目ではなく、レースの見立て。

## 基本ルール

- netkeita本体・既存バックエンドエンジンは改修しない。
- 穴党参謀AI専用スクリプトだけを追加する。
- 既存APIや生成済みJSONLを読み取り専用で使う。
- 最初から購入推奨にしない。
- まず「フォワード検証ログ」として運用する。
- 的中率や回収率だけでなく、ユーザーが読んで判断しやすい情報を出す。

## 既存資産

必読:

- `docs/anatou_wide_rebirth_final_report_20260525.md`
- `docs/anatou_pair_phase1_summary_20260525.md`

レース単位データセット:

- `data/wide_rebirth_dataset_api_jra_20260301_20260430.jsonl`
- `data/wide_rebirth_dataset_api_nar_20260301_20260430.jsonl`

ペア単位データセット:

- `data/anatou_pair_dataset_jra_20260301_20260430.jsonl`
- `data/anatou_pair_dataset_nar_20260301_20260430.jsonl`

既存スクリプト:

- `scripts/build_wide_rebirth_dataset_from_api.py`
- `scripts/wide_rebirth_backtest.py`
- `scripts/anatou_pair_dataset.py`
- `scripts/anatou_pair_backtest.py`
- `scripts/run_backend_predictions_only.py`

## 最終サービス像

### 毎日出すコンテンツ

```text
穴党参謀AI 本日のレース診断

注目レース:
- 中山8R 荒れ警戒
- 阪神10R AI一致
- 船橋7R 人気馬危険

危険人気馬:
- 中山8R 3番

AI穴馬:
- 中山8R 8番

見送り:
- 人気とAI評価が噛み合わないレース
- 妙味候補がないレース
```

### レースごとの診断項目

- `race_id`
- `date`
- `race_type`
- `venue`
- `race_number`
- `field_size`
- `ai_consensus_score`
- `ai_disagreement_score`
- `market_gap_score`
- `hole_candidate_count`
- `danger_popular_count`
- `volatility_score`
- `watch_score`
- `primary_label`
- `labels`
- `consensus_horses`
- `ai_hole_horses`
- `danger_popular_horses`
- `suggested_use`
- `summary_text`

### ラベル

- `ai_consensus`
- `ai_disagreement`
- `market_gap`
- `hole_candidate`
- `danger_popular`
- `solid`
- `volatile`
- `skip`
- `watch`

### suggested_use

- `skip`
- `read_only`
- `hole_check`
- `danger_popular_check`
- `solid_reference`
- `forward_watch`

## スコア設計

### AI一致度

見るもの:

- 各馬が何基のエンジンtop5に入ったか
- top3支持が何基あるか
- 最多支持馬の支持数
- 上位支持馬が何頭に集中しているか

高いほど:

- AIの意見が揃っている
- 堅実寄りまたは軸候補がいる

### AI意見割れ

見るもの:

- top5に出てくるユニーク馬数
- 最多支持馬の支持が弱い
- 各エンジンのtop1がバラバラ

高いほど:

- 混戦
- 見送りまたは荒れ警戒

### 市場ギャップ

見るもの:

- 5人気以下なのに複数エンジンがtop5
- 1〜3人気なのにAI支持が弱い
- AI評価順位と人気順位のズレ

高いほど:

- AI穴馬や危険人気馬がいる

### 荒れ度

見るもの:

- AI穴馬候補数
- 危険人気馬数
- AI意見割れ
- 人気中位馬へのAI支持

高いほど:

- 穴党向けに読む価値あり

### 見送り判定

見送り条件:

- AI支持が薄い
- 人気とのズレがない
- 穴馬候補がいない
- 危険人気馬もいない
- レース診断として特徴が薄い
- 過去ペア検証で不利な条件に該当

## 開発フェーズ

## Phase 1: レース診断データセット作成

目的:

既存レース単位JSONLから、レースごとの診断スコアを作る。

作るファイル:

- `scripts/anatou_race_diagnosis.py`

入力:

- `data/wide_rebirth_dataset_api_jra_20260301_20260430.jsonl`
- `data/wide_rebirth_dataset_api_nar_20260301_20260430.jsonl`
- 必要に応じて `data/anatou_pair_dataset_*.jsonl`

出力:

- `data/anatou_race_diagnosis_jra_20260301_20260430.jsonl`
- `data/anatou_race_diagnosis_nar_20260301_20260430.jsonl`
- `docs/anatou_race_diagnosis_build_*.md`
- `docs/anatou_race_diagnosis_samples_*.md`

完了条件:

- JRA/NARで診断JSONLが生成できる
- ラベル別件数が出る
- 注目レースサンプルが読める

## Phase 2: 診断ラベルの妥当性検証

目的:

診断ラベルごとに、実際にどういう傾向があるかを見る。

作るファイル:

- `scripts/anatou_race_diagnosis_backtest.py`

見るもの:

- ラベル別のワイド全体ROI
- AI穴馬の複勝圏率
- 危険人気馬の馬券圏外率
- 荒れ警戒レースの高配当発生率
- 見送りレースの低妙味率

重要:

ここでも「買い目ROI」だけを目的にしない。

見るべき価値:

- 危険人気馬が本当に危険か
- AI穴馬が馬券内に来やすいか
- 荒れ警戒ラベルが高配当レースを拾えているか
- 見送りラベルが特徴薄いレースを除外できているか

## Phase 3: 今日の診断生成

目的:

今日のレースに対して診断を出す。

作るファイル:

- `scripts/anatou_today_diagnosis.py`

出力:

- `data/anatou_today_diagnosis_YYYYMMDD.jsonl`
- 標準出力の診断サマリ

最初はTelegramへ送らない。

## Phase 4: フォワード検証ログ

目的:

日々の診断を保存し、結果と突合する。

作るファイル:

- `scripts/anatou_forward_diagnosis_log.py`
- `scripts/anatou_forward_diagnosis_results.py`

保存するもの:

- 診断ラベル
- AI穴馬
- 危険人気馬
- 見送り判定
- 結果
- 的中/不的中ではなく、診断が妥当だったか

## Phase 5: Telegram配信化

目的:

穴党参謀AI Telegramを「検証ログ型レース診断AI」に変更する。

配信文面:

```text
穴党参謀AI 本日のレース診断

これは購入推奨ではなく、AIによるレース診断のフォワード検証です。
```

配信項目:

- 今日の注目レース
- AI穴馬
- 危険人気馬
- 見送り推奨レース
- 参考メモ

注意:

- 旧回収率訴求を使わない
- 購入推奨と断定しない
- `Dlogic/GANTZ` 露出禁止
- netkeitaとは別プロダクトとして扱う

## Phase 6: 本サービス化判定

本サービス化条件:

- フォワード検証期間を最低4週間
- AI穴馬の複勝圏率が人気期待値より高い
- 危険人気馬の凡走率が十分高い
- 見送り判定がユーザー価値として説明できる
- 買い目を出す場合は、別途ROI基準を満たす

停止条件:

- 診断ラベルの妥当性が崩れる
- フォワード検証で危険人気馬/AI穴馬の精度が低い
- 買い目化した場合にROIが基準未満

## 実装上の注意

- 既存エンジンは触らない。
- `api/data_api.py` など既存配信ロジックは、Phase 5までは改修しない。
- まずローカルJSONLとdocsレポートで検証する。
- 生成物は `data/` と `docs/` に置く。
- 新しいCodexはこの計画書、最終レポート、Phase 1サマリを読んでから進める。

## 次にやること

1. `scripts/anatou_race_diagnosis.py` を作る。
2. JRA/NARの診断JSONLを生成する。
3. 診断ラベル別件数とサンプルを出す。
4. `scripts/anatou_race_diagnosis_backtest.py` に進む。

