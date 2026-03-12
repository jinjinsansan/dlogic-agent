# MYBOT機能 仕様書・実装計画

## 概要
ユーザーが自分だけのAI競馬予想BOTを作成できる機能。
IMLogicエンジン（12項目のウェイトをカスタマイズ可能）をベースに、
ユーザーごとに異なる予想結果を提供する。

## 決定事項
- **プラットフォーム**: WebApp専用（LINE Botには組み込まない）
- **BOT数**: 1人1BOT（編集して使い回し）
- **認証**: Google認証（旧Dlogic踏襲、Supabase連携）
- **DB**: Supabase `v2_imlogic_settings` テーブル（既存）

## 完了済み
- [x] IMLogic予想APIエンドポイント（VPS port 8000）
  - `POST /api/v2/predictions/imlogic`
  - 12項目ウェイト + 馬/騎手比率で予想実行
  - 動作確認済み（2026-03-12）

## ページ構成
```
/mybot          → LP（ランディングページ）
/mybot/settings → 設定画面（BOT作成/編集）
/mybot/chat     → MYBOTチャット画面
```

## Phase 1: MYBOT作成（MVP）

### 1-1. LP（/mybot）
- IMLogicの説明（自分だけのAI予想エンジンを作れる）
- 12項目カスタマイズのビジュアル説明
- プリセット紹介（バランス型/血統重視/タイム重視/騎手重視）
- CTA「無料でBOTを作る」→ Google認証 → 設定画面へ

### 1-2. 設定画面（/mybot/settings）
- BOT名入力
- 馬/騎手 比率スライダー（合計100%）
- 12項目ウェイトスライダー（合計100%）
- プリセットボタン（ワンタップで値セット）
- 保存 → Supabase `v2_imlogic_settings`
- 既存設定がある場合は編集モードで表示

### 1-3. MYBOTチャット（/mybot/chat）
- 既存WebAppチャットUIを流用（LINE風UI）
- ヘッダーにBOT名表示
- 「予想して」→ IMLogic APIをユーザーのウェイトで呼び出し
- 通常4エンジン予想の代わりにIMLogic結果を表示

### 1-4. 認証
- Google認証（NextAuth.js、既存実装あり）
- Supabase usersテーブル連携（旧Dlogicユーザー引き継ぎ）

## Phase 2: 成績・公開

### 2-1. 成績追跡
- MYBOTの予想結果をSupabaseに記録
- 的中率・回収率を自動計算
- 設定画面に成績サマリー表示

### 2-2. BOT公開・購読
- 公開フラグ設定
- 公開BOT一覧ページ（/mybot/explore）
- 他ユーザーのBOTを「購読」して予想を見る
- BOTランキング（回収率順）

## 12項目ウェイト一覧
| # | キー | 日本語名 | デフォルト |
|---|---|---|---|
| 1 | distance_aptitude | 距離適性 | 8.33% |
| 2 | bloodline_evaluation | 血統評価 | 8.33% |
| 3 | jockey_compatibility | 騎手適性 | 8.33% |
| 4 | trainer_evaluation | 調教師評価 | 8.33% |
| 5 | track_aptitude | コース適性 | 8.33% |
| 6 | weather_aptitude | 天候適性 | 8.33% |
| 7 | popularity_factor | 人気指数 | 8.33% |
| 8 | weight_impact | 斤量影響 | 8.33% |
| 9 | horse_weight_impact | 馬体重影響 | 8.33% |
| 10 | corner_specialist | コーナー得意 | 8.33% |
| 11 | margin_analysis | 着差分析 | 8.33% |
| 12 | time_index | タイム指数 | 8.37% |

## プリセット
| 名前 | 馬:騎手 | 特徴 |
|---|---|---|
| バランス型 | 70:30 | 全項目均等 |
| 血統重視型 | 80:20 | bloodline_evaluation 40% |
| タイム重視型 | 90:10 | time_index 50% |
| 騎手重視型 | 50:50 | jockey_compatibility 25% |

## API
| エンドポイント | 用途 | 状態 |
|---|---|---|
| `POST /api/v2/predictions/imlogic` | IMLogic予想実行 | ✅ 完了 |
| `GET /api/v2/imlogic/settings` | ユーザー設定取得 | 既存（要認証調整） |
| `POST /api/v2/imlogic/settings` | 設定保存 | 既存（要認証調整） |
| `GET /api/v2/imlogic/presets/list` | プリセット一覧 | 既存 |

## 既存リソース（流用可能）
- **バックエンド**: `chatbot/uma/backend/services/imlogic_engine.py` → VPSに既存
- **設定API**: `chatbot/uma/backend/api/v2/imlogic_settings.py` → VPSに既存
- **フロントUI**: `src/app/v2/my-account/page.tsx` にスライダーUI実装あり
- **コミュニティ**: `src/components/v2/imlogic/` に投稿・コメント・シェア機能あり
- **DB**: `v2_imlogic_settings`, `v2_imlogic_posts`, `v2_imlogic_comments` テーブル既存

## デザイン
- フロントエンドのデザインシステム: Binance風ダークテーマ
- メインカラー: #0B0E11（背景）, #F0B90B（ゴールド）, #EAECEF（テキスト）
- フォント: Noto Sans JP + Bebas Neue
- アニメーション: framer-motion
