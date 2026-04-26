# マルチ馬券種分析プラン

**作成日**: 2026-04-26
**起案者**: jin (オーナー) + Claude
**目的**: 単勝のみで運用している現エンジン分析を、複勝・ワイド・3連複・馬連まで拡張し、新たな "特異点" を発見する

---

## 0. 背景・現状

### これまでに構築済みのもの (2026-04-26時点)

| 成果物 | パス | 内容 |
|---|---|---|
| エンジン精度監査レポート | `docs/engine_accuracy_audit_20260425.md` | 4エンジン × 8,375レース分の単勝回収率分析、黄金パターン特定 |
| 黄金パターン検出ページ | `/v2/golden-pattern` (フロント) + `/api/data/golden-pattern/today` (バックエンド) | 当日 + 過去46日分のレース予想をブラウザ表示、結果+P/L付き |
| 過去スナップショット | `data/golden_history/{YYYYMMDD}.json` | 3/11〜4/25 (46日分) のスナップショット保存済み |
| 黄金パターン自動cron | `vps_cron_results.py` Step 3 | 毎晩21-22時に当日snapshot生成 |
| 穴党AI参謀チャンネル | Telegram channel `-1003987167999` (Bot @anatoukeibabot) | 毎朝08:00/09:00/09:30 自動配信中 |

### 監査で判明している事実 (単勝)

- 4エンジン (Dlogic / Ilogic / ViewLogic / MetaLogic) のS本命の**単勝回収率は60〜80%** (ランダム同等〜微弱)
- 「**2-3エンジン一致 × 5-8番人気**」フィルタで**回収率169-215%** に跳ね上がる ("緩い黄金パターン")
- 「+ NAR + 5強競馬場 + 6-12頭 + 火水木」追加で**回収率450%** ("厳格黄金パターン")
- ただし **単勝のみで分析してきた** = エンジンが出している top5 予想のうち1位 (S本命) しか活用していない

### 未活用の情報

各エンジンは **top5 予想** を出している:
- **S** (top1, 本命◎)
- **A** (top2, 対抗○)
- **B** (top3, 単穴▲)
- **C** (top4, 連下△)
- **D** (top5, 穴×)

`engine_hit_rates` テーブルには `top1_horse` と `top3_horses` (=S, A, B の3頭) が保存されているが、**top4/top5 (C, D) は記録されていない**。3着以内予測は3頭まで。

---

## 1. 新しい仮説と分析方向

### 主要仮説

各馬券種ごとに、エンジン群が異なる強みを持っている可能性がある:

| 馬券種 | 仮説 | 期待度 |
|---|---|---|
| **複勝** | dlogic S本命の複勝率41.7%は既にランダム超え。複勝オッズが取れれば即実用可能性高い | ★★★★★ |
| **ワイド** | エンジン top3 が3着内2頭一致する確率 25.1% (dlogic) → ワイド回収率次第で大化け | ★★★★☆ |
| **3連複** | 4エンジン × top3 = 12頭の予想集合。合議が高い3頭組合せの的中率と配当 | ★★★★☆ |
| **馬連** | 1着-2着の予想精度未測定。複合エンジンで強い特定組合せが見つかる可能性 | ★★★☆☆ |
| **3連単** | 期待値は高いが当てるのが極端に難しい。サンプル不足のリスク | ★★☆☆☆ |

### "特異点" 発見の例 (まだ未検証)

- **複勝 × 厳格パターン**: S本命複勝率がさらに上がる組合せ?
- **ワイド × 2エンジン一致**: 一致した2頭をワイドBOX買い → 回収率は?
- **3連複 軸1頭流し**: 合議制本命を軸に、他エンジン推し馬2-3頭を相手に流す
- **特定エンジンの強み**: viewlogic は単勝弱いが、3連複の3着候補としては機能する? など

---

## 2. 最大の制約 (重要)

**`race_results.result_json` には単勝払戻 (`win_payout`) しか入っていない**。

具体的に欠落しているデータ:
- 複勝払戻 (各馬の複勝金額)
- 馬連 / 馬単 払戻
- ワイド (複合勝枠) 払戻
- 3連複 / 3連単 払戻

現在 8,375件のengine_hit_rates × 2,165件のrace_results が揃っているが、**払戻データを別途取得しない限り何も分析できない**状態。

---

## 3. フェーズ計画 (3段階)

### Phase A: 払戻データ取得・整備 (推定: 半日〜1日)

**ゴール**: 過去全期間 + 今後すべてのレースで、複勝・馬連・ワイド・3連複・3連単 の払戻金額を保存する状態にする。

**作業項目**:

A-1. **既存スクレイパー調査**
- `scrapers/race_result.py` の現状機能を確認
- netkeiba結果ページから取得しているフィールドを確認
- 払戻データを既に取っているが捨てているのか、そもそも取っていないのかを判別

A-2. **スクレイパー拡張**
- 結果ページの「払戻」セクション全種をパース
- データ構造案 (race_results.result_json への追加):
  ```json
  {
    "top3": [...],
    "total_horses": N,
    "payouts": {
      "win": 250,
      "place": [{"horse_number": 12, "payout": 130}, ...],
      "umaren": {"combo": [12, 7], "payout": 1840},
      "wide": [{"combo": [12, 7], "payout": 480}, ...],
      "sanrenpuku": {"combo": [12, 7, 10], "payout": 5230},
      "sanrentan": {"combo": [12, 7, 10], "payout": 18420},
      "umatan": {"combo": [12, 7], "payout": 3640}
    }
  }
  ```

A-3. **過去分リトロアクティブ取得**
- 既存 race_results 2,165件を1件ずつnetkeibaから再取得
- バックフィルスクリプト `scripts/backfill_payouts.py` を新規作成
- レート制限考慮 (1秒1件 → 約30分)
- 進捗ログ + 失敗時の retry機構

A-4. **今後の自動取得**
- `vps_cron_results.py` 内の結果取得処理に payouts 取得を組込み
- もしくは別 cron で毎晩実行

A-5. **データ整合性チェック**
- 取得後、サンプル数件を手動で netkeiba と突き合わせて誤差ゼロ確認
- 取得失敗率を集計

### Phase B: 複勝・ワイド分析 (推定: 1日)

**ゴール**: 単勝分析と同レベルの監査レポートを複勝・ワイドで作成し、新しい "特異点" を発見する。

**作業項目**:

B-1. **複勝回収率分析** (新スクリプト `scripts/place_recovery_analysis.py`)
- 各エンジン S本命の複勝回収率 (全期間)
- JRA/NAR別、競馬場別、人気別、頭数別、曜日別
- 黄金パターン × 複勝の組合せ → "複勝黄金パターン" 候補発見

B-2. **ワイド分析** (新スクリプト `scripts/wide_recovery_analysis.py`)
- エンジン top3 から2頭ピックアップ → ワイドBOX or 流し
- 戦略パターン:
  - **エンジン top1+top2 でワイド**
  - **2エンジン以上が一致した2頭でワイド**
  - **合議制本命 + 他エンジン推し馬 1点ずつ流し**
- 各戦略の的中率・回収率
- 過去比較で "ワイド黄金パターン" 抽出

B-3. **総合監査レポート更新**
- `docs/engine_accuracy_audit_YYYYMMDD.md` (新版)
- 単勝・複勝・ワイドの3券種を統合した結論
- マルチ馬券種運用ルールの提案

### Phase C: 3連複・馬連分析 (条件付き、推定: 1〜2日)

**前提**: Phase B で複勝・ワイドの数字が出揃って、追加分析の価値があると判断した場合に進む。

**作業項目**:

C-1. **3連複分析** (新スクリプト `scripts/sanrenpuku_analysis.py`)
- 戦略パターン:
  - **4エンジンtop3集合の頻出3頭BOX**
  - **合議制本命を軸 → 他エンジン推し馬2-3頭流し**
  - **3エンジン以上一致でフィルタ**
- 1点 / 3点 / 6点流しの効率比較

C-2. **馬連分析** (新スクリプト `scripts/umaren_analysis.py`)
- top1+top2 (S+A) の的中率
- 2エンジン本命一致の馬連
- ボックス vs 流し の比較

C-3. **馬券構成最適化**
- 1日の予算配分: 単勝 + 複勝 + ワイド + 3連複 でどう割り振ると期待値最大か
- 黄金パターン1レース当たりの推奨買い目セット

---

## 4. データソースと参考情報

### 主要DBテーブル (Supabase)

| テーブル | 行数(2026-04-25時点) | 含まれる情報 |
|---|---|---|
| `engine_hit_rates` | 8,375 | 4エンジン × top1_horse + top3_horses + hit_win + hit_place |
| `race_results` | 2,165 | race_id, race_date, venue, race_name, winner_number, win_payout, **result_json (top3 + total_horses のみ)** |
| `odds_snapshots` | 123,335 | レース直前オッズ。人気順位の根拠データ |

### 既存スクリプト (再利用候補)

- `scripts/check_engine_results.py` — エンジン的中率計算 (日次cron)
- `scripts/fetch_results.py` — 未判定予想の追加処理
- `scripts/rank_analysis.py` — 単勝ランク別分析
- `scripts/recovery_analysis.py` — 単勝回収率分析
- `scripts/popularity_analysis.py` — 対人気優位性
- `scripts/consensus_analysis.py` — エンジン組合せ精度
- `scripts/segment_analysis.py` — セグメント別精度

### Netkeibaスクレイピング既存実装

- `scrapers/race_result.py` — レース結果スクレイパー
- `scrapers/odds.py` — リアルタイムオッズスクレイパー
- 結果ページURL: `https://race.netkeiba.com/race/result.html?race_id={netkeiba_id}` (JRA)
- 結果ページURL: `https://nar.netkeiba.com/race/result.html?race_id={netkeiba_id}` (NAR)
- race_id変換: `tools/executor.py` の `_resolve_netkeiba_race_id`

### VPS実行コマンド

```bash
# スクリプト実行
ssh root@220.158.24.157 "cd /opt/dlogic/linebot && source venv/bin/activate && python scripts/<name>.py"

# scp デプロイ
scp scripts/<name>.py root@220.158.24.157:/opt/dlogic/linebot/scripts/

# サービス再起動
ssh root@220.158.24.157 "systemctl restart dlogic-linebot"
```

### Supabase接続注意

- **ローカル `.env.local` には Supabase鍵が無い** (CLAUDE.mdとは齟齬がある状態)
- 必ずVPSで実行する。VPSの `.env.local` に `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` が設定済み

---

## 5. 新チャットで再開する際の手順

このプランを別Claudeに引き継ぐ場合:

### Step 1: 現状把握
1. このファイル (`docs/multi_ticket_analysis_plan.md`) を読む
2. 監査レポート (`docs/engine_accuracy_audit_20260425.md`) を読む
3. 黄金パターンページのメモ (`memory/project_golden_pattern_page.md`) を読む
4. 穴党チャンネルのメモ (`memory/project_anatou_channel.md`) を読む

### Step 2: 開始判断
- jin に「Phase A から始めるか / Phase B 直接か」確認
- 複勝/ワイドだけでも十分なら Phase B のみでスコープ縮小可

### Step 3: 着手
- **Phase A から開始する場合**: 最初に `scrapers/race_result.py` を読んで、現状の payout 取得状況を確認
- **Phase B 直接の場合**: そもそも payout データが揃っていないので無理 — Phase A 必須

### よくある罠 (引き継ぎ事項)

1. **race_id 形式に2種類ある**:
   - 内部形式: `20260423-中山-7` (date-venue-num)
   - netkeiba形式: 12桁数字
   - JOIN時は (date, venue, race_number) で行う必要あり (odds_snapshots 等)
2. **race_results.race_number は存在しない** (race_id から抽出する)
3. **prefetch JSON は直近9日分のみ保持**。古い日付は snapshot fallback で対応済み
4. **scripts は VPS 実行が必須** (ローカル .env.local に Supabase鍵が無い)
5. **Droidの改修コードは尊重** (CLAUDE.mdに明記、勝手に上書きしない)

---

## 6. 概算スケジュール (本格着手時)

| Phase | 作業 | 推定 |
|---|---|---|
| A | スクレイパー調査・拡張・既存分リトロアクティブ取得・cron組込み | **半日〜1日** |
| B | 複勝・ワイド分析・監査レポート更新 | **1日** |
| C | 3連複・馬連 (条件付き) | **1〜2日** |

合計: **2〜4日** (集中作業ベース)

---

## 7. 期待される成果物

### Phase A 完了時
- `race_results.result_json.payouts` に全馬券種の払戻が保存された状態
- 過去 2,165件のリトロアクティブ取得完了
- 今後の自動取得が cron で動作

### Phase B 完了時
- 監査レポートv2 (`docs/engine_accuracy_audit_v2_<DATE>.md`)
- 複勝・ワイドの "黄金パターン" 候補レポート
- 穴党参謀チャンネルでの新コンテンツ案 (複勝買い目案・ワイド買い目案)

### Phase C 完了時 (条件付き)
- 3連複・馬連の戦略レポート
- マルチ馬券種統合運用ルール
- "1日の最適買い目セット" の提案

---

## 8. 補足: なぜこの順序か (設計判断の記録)

- **Phase A を最初にする理由**: データが無ければ何も分析できない。投資する価値があるかすら判断不能
- **複勝・ワイドを最優先する理由**:
  - 既存データ (place_hit_count, top3_horses) との整合性が高い
  - 同じスクレイピング1回で両方取れるのでコスト効率最良
  - 穴党チャンネル運用にすぐ乗せられる (買い目追加で済む)
- **3連複・馬連を後回しにする理由**:
  - 戦略パターン数が組合せ爆発的に多い → 設計時間が長い
  - 1点購入金額が大きく、リスク管理が複雑になる
  - 複勝・ワイドの数字を見てから判断すれば、ROIの低い分析を回避できる

---

**プラン承認**: 必要 (jinが「Phase A 着手OK」と明示してから開始)
**最終更新**: 2026-04-26
