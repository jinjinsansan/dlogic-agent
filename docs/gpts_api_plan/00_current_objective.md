# GPTs向けパブリックAPI構築 — 現在の目的と進行状況

最終更新: 2026-04-21

## 今やろうとしていること(一文)

DlogicAIのナレッジを **GPTs(Custom Actions)向けに公開する軽量JSONを用意し、Cloudflare R2経由で配信する** 準備。調査フェーズが完了し、次は一回限りの生成スクリプト実装に進む。

## ゴール

1. **3種類の軽量JSON** を GPTs から直接フェッチできる形でR2に配置する
   - `public/gpts_jockey_stats.json` — 主要騎手 (50人程度) の会場×距離別成績サマリ
   - `public/gpts_course_insights.json` — JRA全コースの人気傾向・波乱度
   - `public/gpts_bloodline_insights.json` — 主要種牡馬・母父の産駒成績
2. **本業サービス(LINE Bot・WebChat・note・トルネードAI)を食わない**範囲に絞る
3. **1日5回/ユーザー**程度のレート制限で「試食」的な立ち位置に留める
4. 最終的にCloudflare Workersで軽量APIラッパを被せるが、**まずはR2直配信で MVP を動かす**

## これまでの調査結果サマリ

### 第1弾: バックエンド全体構造調査
→ [`01_backend_research.md`](./01_backend_research.md)

- リポジトリは2つ: `dlogic-agent` (LINE Bot, Flask:5000) + `chatbot/uma/backend` (FastAPI:8000)、どちらもVPS(Xserver)に常駐
- **Cloudflare Workers は未使用**。Workers前提だった当初の想定は修正
- Cloudflare R2 は既に使用中(バケット `dlogic-knowledge-files`)
- 既存の認証なしエンドポイント `/api/data/*` が存在(dlogic-note配信用)
- 予想エンジン系APIは合計70+、Supabase連携・Redis連携あり

### 第2弾: R2バケット詳細調査
→ [`02_r2_research.md`](./02_r2_research.md)

- **R2バケットは Public Access 有効**(`pub-059afaafefa84116b57d57e0a72b81bd.r2.dev`)
- アップロードは週次(月曜12:00)+日次プリフェッチの2系統
- `*_latest.json` エイリアス運用で4種類のナレッジが更新中
- ⚠️ **セキュリティ問題**: R2キーがソースコードに平文ハードコード済み (要ローテーション)
- カスタムドメイン未設定、CORS設定はダッシュボード確認必要

### 第3弾: 一回限り生成スクリプトの計画
→ [`03_oneshot_plan.md`](./03_oneshot_plan.md)

- 騎手データソース: R2 `jra_jockey_knowledge_latest.json` (推奨) or ローカル `jockey_knowledge.json` (93MB, 846騎手)
- コース傾向: ローカル `dlogic_raw_knowledge.json` (292MB, 39,674頭) から集計必要 — 専用ファイルなし
- 血統データ: 同じく生データから `sire` / `broodmare_sire` フィールドを集計
- 既存 `scripts/simple_r2_upload.py` の関数を流用可能
- 配置推奨: `chatbot/uma/backend/scripts/generate_gpts_knowledge.py`
- 実行時間見込み: 1〜2分

## 次にやること

1. **仁さんの意思決定待ち** (03_oneshot_plan.md 付記参照)
   - 騎手の絞り込み人数 (推奨: 50人)
   - コース集計の最小レース数 (推奨: 100)
   - 血統の最小産駒数 (推奨: 100)
   - データソース: R2の`_latest`取得 or ローカルファイル直読み
2. **R2キーのローテーション**(GPTs API公開とは別動線で先にやるのが安全)
3. **`generate_gpts_knowledge.py` 実装**(一回限りスクリプト)
4. 実行 → 3種JSONをR2にアップロード
5. パブリックURL動作確認(curl HEAD)
6. GPTs Custom Actions 用の OpenAPI スキーマ作成

## まだ決まっていないこと (不明・要確認)

| 項目 | 必要な確認先 |
|---|---|
| R2バケットのCORS設定 | Cloudflareダッシュボード |
| `jra_knowledge_latest.json` / `jra_jockey_knowledge_latest.json` の現在サイズ | R2ダッシュボード or curl HEAD |
| JRA-VAN / netkeiba の再配布規約抵触範囲 | 仁さんの規約確認 |
| GPTsからの利用者識別子ヘッダ仕様 | 実機検証必要 |
| カスタムドメイン方針 (`api.dlogicai.in` 等) | 仁さんの命名決定 |

## 制約・前提

- コード変更なし、**調査・計画のみ**のフェーズが完了
- 次フェーズの実装も**新規ファイル作成のみで既存ファイルに手を入れない**方針
- Droid(factory-droid)が触っている領域には干渉しない
- 作業順序: 鍵ローテ → 軽量JSON生成 → R2アップロード → 動作確認 → (後日)Workers実装

## 成果物インデックス

| ファイル | 内容 |
|---|---|
| [`00_current_objective.md`](./00_current_objective.md) | 本ファイル。現在地と次のアクション |
| [`01_backend_research.md`](./01_backend_research.md) | Flask/FastAPIバックエンド全体構造 + Cloudflare関連調査 |
| [`02_r2_research.md`](./02_r2_research.md) | R2バケット詳細 + 認証/公開設定/Workers移行前提 |
| [`03_oneshot_plan.md`](./03_oneshot_plan.md) | 軽量JSON3種の生成・アップロード計画(疑似コード含む) |
