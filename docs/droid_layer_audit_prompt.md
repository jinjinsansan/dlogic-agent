# Droid 検証プロンプト — 穴党参謀AI Layer 1 / Layer 3 独立監査

最終更新: 2026-05-01
用途: factory-droid に Layer 1 / Layer 3 の統計的妥当性を独立検証させる

---

## 使い方

下記の「プロンプト本体」セクションをそのまま Droid にコピペして投げてください。

---

## プロンプト本体

```
あなたには、競馬予想 AI システム「穴党参謀AI」の運用ルール（Layer 1 / Layer 3）について
独立した統計的監査を実施してほしい。

## 背景

「穴党参謀AI」は dlogic-agent プロジェクト（VPS 稼働中）が note 記事および Telegram で
配信している予想システム。以下 2 つの戦略を運用している：

**Layer 1 — NAR本命厳格 単勝**
- 条件: NAR + 火水木 + 6-12頭立て + 5-8人気 + 旧強5会場（門別/船橋/大井/川崎/盛岡）
       + 4エンジン top1 で 2-3 一致
- 既存報告: 回収率 396.9% / Bootstrap 95% CI下限 225% / n=145（clean 2ヶ月）

**Layer 3 — JRA S級（週末のみ）**
- F5複勝: 4エンジン中 3 以上の top3 一致馬 → 複勝1点
  - 既存報告: 131% / CI下限 118% / n=590
- U2馬連BOX3: 4エンジン top3 投票合議の上位3頭 → 馬連BOX 3点
  - 既存報告: 326% / CI下限 213% / n=1116
- S1三連複1点: 同上3頭 → 三連複1点
  - 既存報告: 837% / CI下限 231% / n=372

これらは過去に複数回修正された経緯あり：
- v3 → v4 → v5 で leakage（情報汚染）が発覚し、ルール全面刷新済み
- 1 年データの 76% が後付け再評価で未来情報を含んでいた問題が判明
- clean データ（leakage 除去後）で再導出されたのが現行 v6 ルール

## プロジェクト場所

- ローカル: `E:\\dev\\Cusor\\dlogic-agent`
- VPS: `ssh root@220.158.24.157` → `/opt/dlogic/linebot/`
- Git tag: `b75b48f`（Plan A 3層自動投票デプロイ時点）

## 検証対象スクリプト

### Layer 1 系
- `scripts/weekday_strict_search.py` — 曜日別 100%+ 回収率セグメント発見
- `scripts/nar_deep_pop_filter.py` — 人気範囲 × 会場 × 軸構成マトリクス（Bootstrap 95% CI 付き）
- `scripts/pckeiba_long_backtest.py` — 火水木 + 強5会場 + 6-12頭 + 5-8人気 フィルタの長期検証（2020〜2026）
- `scripts/v5_clean_eval.py` — leakage 除去後 v5 ルール再評価
- `scripts/full_validation_clean.py` — 全戦略 × 全馬券種 × 全フィルタの完全検証（最終確認用）

### Layer 3 系
- `scripts/multi_ticket_consensus_backtest.py` — 4エンジン top3 投票合議で全馬券種セグメント化（**Layer 3 主犯**）
- `scripts/analyze_engine_split_view.py` — JRA / NAR 完全分離集計

### 補助
- `scripts/popularity_analysis.py` / `top5_analysis.py` / `consensus_analysis.py`
- `scripts/recovery_analysis.py` / `place_recovery_analysis.py` / `wide_recovery_analysis.py`
- `scripts/segment_analysis.py` / `nar_full_period_analysis_v2.py`
- `scripts/golden_frequency.py` / `rank_analysis.py`

## 既存レポート（docs/）

過去の分析結果はすべて MD で保存されている：
- `engine_accuracy_audit_v5_FINAL_20260427.md` — 最終監査（v5確定版）
- `multi_ticket_consensus_backtest_20260427.md` — Layer 3 根拠
- `nar_deep_pop_filter_20260427.md` — Layer 1 根拠
- `full_validation_clean_20260427.md` — clean 検証
- `pckeiba_long_backtest_2020_to_2026.md` — 長期検証
- `engine_split_analysis_20260427.md` — JRA/NAR 分離分析

これらを **まず読んだ上で** 監査を始めてほしい。

## データソース

- **Supabase `engine_hit_rates`**: 1 年分の 4エンジン top1 / top3 結果
- **PCKEIBA**: `nvd_hr` / `jvd_hr`（NAR/JRA の全7馬券種払戻データ）+ `nvd_se` / `jvd_se`（馬番・人気・着順）
- 認証情報は `.env.local`（VPS 上）に格納

## 監査ポイント（優先順）

### 1. Leakage の再確認（最重要）

過去に「1年データの 76% が後付け再評価」という事故があった。clean ロジックが
本当に十分か、未来情報の混入が完全に消えているか確認してほしい。

- v5_clean_eval.py / full_validation_clean.py の clean 化処理を読み解く
- 入力データ（engine_hit_rates）の各列に未来情報が含まれていないか
- 検証時の train/test 分割（または時系列スプリット）が適切か

### 2. 統計的妥当性

- Bootstrap 95% CI の計算方法が標準的か（リサンプリング数、置換可否）
- サンプルサイズが結論に対して十分か
  - Layer 1: n=145 はやや少なめ、CI下限 225% の信頼性は？
  - Layer 3 S1: n=372、CI下限 231% / 中心値 837%、CI 幅が広すぎないか
- p-hacking の疑い（多重検定問題）— 複数の組み合わせを試した中で偶然プラスになっただけの可能性

### 3. 再現性

- 同じスクリプトを再走して既存レポートと同じ数字が出るか
- データを少し変えた（期間延長 / 期間短縮）ときの安定性
- ランダムシード固定の有無

### 4. 過剰最適化

- Layer 1 の条件は「火水木 + 旧強5会場 + 6-12頭 + 5-8人気 + 2-3エンジン一致」と
  非常に絞り込まれている → 過学習の典型シグネチャ
- このフィルタを使わなかった場合（より緩い条件）の回収率はどれくらい落ちるか？
- Layer 3 S1 の 837% は外れ値（少数の高配当が引っ張っている）ではないか
  - 中央値・第1四分位での回収率はどうか

### 5. 代替戦略の探索（時間あれば）

- Layer 1 / 3 より統計的に強い・安定した戦略が見つかるか
- サンプルサイズと統計的有意性のトレードオフで現行ルールに見直しの余地はあるか
- 例: 条件を1つ緩めて n を増やした場合の CI 比較

## 出力形式

`docs/droid_layer_audit_<YYYYMMDD>.md` に監査レポートとして書いてほしい。

各監査ポイントについて：
- **結論**: PASS / WARN / FAIL のいずれか
- **根拠**: 数字・引用・スクリプト行番号
- **推奨対応**: 修正の必要があれば具体的に

最後に **「Layer 1 / Layer 3 を現行のまま運用継続して良いか」** の総合判断を。

## 制約

- **既存スクリプトを破壊しない**。改良・追加検証用に新スクリプトを書く場合は
  `scripts/audit_<name>.py` のように名前で区別すること
- VPS の Supabase / PCKEIBA は **read-only** クエリのみ
- 結論を急がない。データに基づいた慎重な判断を優先

## 期待するアウトプット

1. レポート `docs/droid_layer_audit_<YYYYMMDD>.md`
2. 必要なら検証用追加スクリプト `scripts/audit_*.py`
3. 重大な問題が見つかった場合は **赤字で警告** を冒頭に
4. 重大な問題がなくても、改善余地があれば「優先度: 中・低」として列挙

レポートが上がったら、jin（プロジェクトオーナー）が運用継続可否を判断する。
```

---

## 補足（jin さんへ）

このプロンプトを Droid に投げる際の注意：

1. **データアクセス**: Droid は VPS に SSH できない可能性が高い。その場合は
   - ローカルの `dlogic-agent` リポジトリを Droid のワークディレクトリに pull させる
   - もしくは Droid に「コードレビューのみ実行 + データへの直接アクセスは jin に依頼する」と明示する

2. **時間配分**: 監査ポイント 1〜4 だけでも数時間〜半日かかる可能性。最初は
   「Leakage 確認のみ」など範囲を絞るのも手。

3. **CLAUDE.md の Droid ルール**: dlogic-agent の CLAUDE.md には
   「Droid が改修したコードは確認済みの正しい修正であり勝手に変更しない」
   という運用ルールあり。Droid の出力は信頼ベースで取り込み、私（Claude）からは
   後付けで上書きしない方針。

4. **比較基準**: 既存の docs/ 配下のレポートと数字が一致するかが「再現性」の基本確認。
   一致しない場合、どちらかが間違っているか、データ更新があった証拠。
