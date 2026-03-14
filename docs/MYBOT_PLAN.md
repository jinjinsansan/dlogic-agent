# MYBOT 実装計画書

## アーキテクチャ概要

```
www.dlogicai.in (Vercel, Next.js) — E:\dev\Cusor\front\d-logic-ai-frontend\
│
├── /                       → 既存TOPページ（変更なし）
├── /mybot                  → ① LP（MYBOTランディングページ）【新規】
├── /mybot/create           → ②③⑤⑥ MYBOT作成・編集ページ【新規】
├── /mybot/[userId]         → ④ ユーザー固有MYBOTチャットページ【新規】
├── /mybot/explore          → みんなのBOTページ（Phase 2）
│
├── /chat                   → 既存チャット（変更なし）
├── /api/chat/*             → proxy → bot.dlogicai.in（既存）
├── /api/chatauth/*         → proxy → bot.dlogicai.in（既存）
├── /api/mybot/*            → proxy → bot.dlogicai.in【新規】
│
bot.dlogicai.in (VPS, Flask, port 5000) — E:\dev\Cusor\dlogic-agent\
├── POST /api/mybot/settings       → MYBOT設定CRUD【新規】
├── POST /api/mybot/chat           → MYBOTチャット（SSE）【新規】
├── POST /api/mybot/upload-icon    → アイコン画像アップロード【新規】
│
VPS backend (FastAPI, port 8000) — 元: E:\dev\Cusor\chatbot\uma\backend\
├── POST /api/v2/predictions/imlogic  → IMLogic予想エンジン（既存稼働中）
├── GET  /api/v2/imlogic/presets/list → プリセット一覧（既存、要登録）
```

## 既存リソース（流用元）

すべて `E:\dev\Cusor\chatbot\uma\` および `E:\dev\Cusor\front\d-logic-ai-frontend\` にある既存コード。

### バックエンド（chatbot/uma/backend/）
| ファイル | 内容 | 状態 |
|---|---|---|
| `services/imlogic_engine.py` | IMLogicエンジン本体（12項目ウェイト計算） | VPS稼働中 |
| `services/local_imlogic_engine.py` | NAR版IMLogicエンジン | VPS稼働中 |
| `api/v2/imlogic_prediction.py` | IMLogic予想APIエンドポイント | VPS稼働中 |
| `api/v2/imlogic_settings.py` | 設定CRUD API（Supabase連携） | VPSに存在、未登録 |

### フロントエンド（front/d-logic-ai-frontend/）
| ファイル | 内容 | 流用方法 |
|---|---|---|
| `src/components/logicchat/IMLogicSettings.tsx` | 12項目トグルカード + 馬/騎手比率スライダー | MYBOT作成ページに移植 |
| `src/components/v2/chat/IMLogicResultCard.tsx` | IMLogic結果表示カード | MYBOTチャットで流用 |
| `src/components/v2/imlogic/IMLogicCommunityList.tsx` | コミュニティ投稿一覧 | Phase 2 みんなのBOTで参考 |
| `src/components/v2/imlogic/SharePostDialog.tsx` | 設定シェアダイアログ | Phase 2 公開機能で参考 |
| `src/services/imlogicCommunityService.ts` | コミュニティAPI通信 | Phase 2で参考 |
| `src/types/logicchat.ts` | `IMLogicSettingsData` 型定義 | そのまま流用 |
| `src/hooks/useChat.ts` | SSEチャット通信 | MYBOTチャットで流用 |
| `src/services/chatService.ts` | チャットAPI通信 | MYBOTチャットで流用 |
| `src/hooks/useLineAuth.ts` | LINE Login認証 | そのまま流用 |

---

## 認証フロー

既存の `/chat` ページと同じLINE Login認証を使い回す。

```
ユーザー → /mybot/create → LINE Login (既存フロー)
                              ↓
                    /api/chatauth/line (既存)
                              ↓
                    Supabase user_profiles (既存UUID)
                              ↓
                    セッショントークン (localStorage)
                              ↓
                    /api/mybot/* にBearer tokenで認証
```

- 既存の `useLineAuth` フック + `chatService.ts` の認証ロジックをそのまま流用
- 同じ `user_profiles` テーブル、同じUUID
- 追加テーブル: `mybot_settings`, `mybot_settings_history`

---

## ページ詳細

### ① LP（ `/mybot` ）【新規ページ】

※ TOPページ（`/`）は一切変更しない。`/mybot` に新規LPを作成。

**構成:**
1. ヒーローセクション — 「自分だけのAI競馬予想BOTを作ろう」
2. 仕組み説明 — 12項目カスタマイズのビジュアル解説
3. プリセット紹介 — バランス型 / 血統重視 / タイム重視 / 騎手重視
4. 3ステップ説明 — ①設定 → ②BOT作成 → ③予想開始
5. CTA — 「無料でMYBOTを作る」ボタン → `/mybot/create`

**デザイン:** 既存サイトのBinance風ダークテーマ踏襲

### ② MYBOT作成・編集ページ（ `/mybot/create` ）

LINE認証必須。未認証ならLINE Loginへリダイレクト。

**セクション構成:**

```
┌─────────────────────────────────┐
│ ⑤ BOTプロフィール設定            │
│  ・BOT名（テキスト入力）          │
│  ・性格（選択式 or テキスト）      │
│  ・口調トーン（選択式）            │
│  ・アイコン画像（デバイスから        │
│    アップロード、プレビュー付き）    │
├─────────────────────────────────┤
│ ③ IMLogic 12項目ウェイト設定      │
│  ※ IMLogicSettings.tsx を移植     │
│  ・馬/騎手 比率スライダー          │
│  ・12項目トグルカード（3列グリッド） │
│  ・ON項目に均等自動配分            │
│  ・プリセットボタン（4種）         │
├─────────────────────────────────┤
│ ⑥ 公開設定                       │
│  ・公開 / 非公開 トグル            │
│  ・公開時の説明文（任意）          │
├─────────────────────────────────┤
│ 編集履歴                          │
│  ・過去の設定一覧（日時付き）       │
│  ・「この設定に戻す」ボタン        │
├─────────────────────────────────┤
│ [BOTを作成する] / [設定を保存]     │
└─────────────────────────────────┘
```

- 初回: 「BOTを作成する」→ 作成後 `/mybot/[userId]` へ遷移
- 2回目以降: 既存設定が読み込まれ編集モード。「設定を保存」→ 履歴に追加、即反映
- 編集履歴: `mybot_settings_history` から取得、ワンクリック復元

### ③ 12項目ウェイト設定

既存 `IMLogicSettings.tsx`（`front/d-logic-ai-frontend/src/components/logicchat/`）を移植。

**12項目（IMLogicSettings.tsxの定義通り）:**

| # | キー | 日本語名 | アイコン |
|---|---|---|---|
| 1 | 1_distance_aptitude | 距離適性 | Ruler |
| 2 | 2_bloodline_evaluation | 血統評価 | Dna |
| 3 | 3_jockey_compatibility | 騎手相性 | Users |
| 4 | 4_trainer_evaluation | 調教師評価 | Award |
| 5 | 5_track_aptitude | トラック適性 | MapPin |
| 6 | 6_weather_aptitude | 天候適性 | Cloud |
| 7 | 7_popularity_factor | 人気要因 | TrendingUp |
| 8 | 8_weight_impact | 斤量影響 | Scale |
| 9 | 9_horse_weight_impact | 馬体重影響 | Activity |
| 10 | 10_corner_specialist | コーナー適性 | RotateCw |
| 11 | 11_margin_analysis | マージン分析 | BarChart |
| 12 | 12_time_index | タイムインデックス | Timer |

**操作方法（既存UIと同じ）:**
- 項目カードをタップでON/OFF
- ON項目に100%を均等自動配分
- 馬/騎手比率: スライダー（0〜100%、10%刻み）
- プリセット4種: バランス型 / 血統重視 / タイム重視 / 騎手重視

### ④ MYBOTチャットページ（ `/mybot/[userId]` ）

ユーザー固有のパラメータURL。

**UI:**
- ヘッダー: BOT名 + アイコン画像
- チャットインターフェース: 既存 `/chat` のSSEチャットUIを流用
- BOTの性格・口調は system prompt に動的注入
- 「予想して」→ ユーザーのIMLogicウェイトで `/api/v2/predictions/imlogic` を呼び出し
- 通常4エンジン予想の代わりにIMLogic結果を表示
- `IMLogicResultCard.tsx` で結果表示
- 公開BOTは他ユーザーもアクセス・利用可能（Phase 2で詳細検討）

### ⑤ BOTプロフィール（エージェント設定）

| 項目 | 型 | 制約 |
|---|---|---|
| bot_name | string | 1〜20文字、必須 |
| personality | string | 選択式（熱血/クール/丁寧/フレンドリー）or 自由入力 |
| tone | string | 選択式（タメ口/敬語/関西弁/博多弁 等） |
| icon_image | file | JPG/PNG、500KB以下、正方形推奨 |

- アイコン画像はSupabase Storageに保存（バケット: `mybot-icons`）
- system promptにBOT名・性格・口調を動的注入

### ⑥ 公開/非公開設定

- デフォルト: 非公開
- 公開ON → `mybot_settings.is_public = true`
- Phase 2で「みんなのBOTページ」（`/mybot/explore`）にリスト表示
- 既存の `IMLogicCommunityList.tsx` / `SharePostDialog.tsx` をPhase 2で参考にする

---

## DB設計

### 新規テーブル: `mybot_settings`

```sql
CREATE TABLE mybot_settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id),

  -- BOTプロフィール
  bot_name TEXT NOT NULL DEFAULT 'MYBOT',
  personality TEXT DEFAULT 'friendly',
  tone TEXT DEFAULT 'casual',
  icon_url TEXT,
  description TEXT,  -- 公開時の説明文

  -- IMLogicウェイト
  horse_weight INTEGER NOT NULL DEFAULT 70,
  jockey_weight INTEGER NOT NULL DEFAULT 30,
  item_weights JSONB NOT NULL DEFAULT '{
    "1_distance_aptitude": 8.33,
    "2_bloodline_evaluation": 8.33,
    "3_jockey_compatibility": 8.33,
    "4_trainer_evaluation": 8.33,
    "5_track_aptitude": 8.33,
    "6_weather_aptitude": 8.33,
    "7_popularity_factor": 8.33,
    "8_weight_impact": 8.33,
    "9_horse_weight_impact": 8.33,
    "10_corner_specialist": 8.33,
    "11_margin_analysis": 8.33,
    "12_time_index": 8.37
  }',

  -- 公開設定
  is_public BOOLEAN NOT NULL DEFAULT FALSE,

  -- メタ
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE(user_id)  -- 1人1BOT
);
```

### 新規テーブル: `mybot_settings_history`

```sql
CREATE TABLE mybot_settings_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES user_profiles(id),

  -- 変更前の全設定スナップショット
  snapshot JSONB NOT NULL,
  -- 変更理由メモ（任意）
  label TEXT,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mybot_history_user ON mybot_settings_history(user_id, created_at DESC);
```

---

## API設計

### VPS Flask側（dlogic-agent、新規 `/api/mybot/`）

| メソッド | パス | 説明 | 認証 |
|---|---|---|---|
| GET | /api/mybot/settings | 自分のMYBOT設定取得 | 必須 |
| POST | /api/mybot/settings | MYBOT作成 or 更新（更新時は履歴自動保存） | 必須 |
| GET | /api/mybot/settings/history | 編集履歴一覧 | 必須 |
| POST | /api/mybot/settings/restore | 履歴から復元（history_id指定） | 必須 |
| POST | /api/mybot/upload-icon | アイコン画像アップロード | 必須 |
| GET | /api/mybot/public/[userId] | 公開BOT情報取得 | 不要 |
| GET | /api/mybot/public/list | 公開BOT一覧（Phase 2） | 不要 |

### MYBOTチャットAPI（新規）

| メソッド | パス | 説明 | 認証 |
|---|---|---|---|
| POST | /api/mybot/chat | MYBOTチャット（SSE） | 必須 |

- 既存 `/api/chat` の `run_agent` をベースに拡張
- `get_predictions` ツール呼び出し時、ユーザーのIMLogicウェイトで `/api/v2/predictions/imlogic` を呼ぶ
- BOTの性格・口調・名前を system prompt に注入

### Next.js proxy追加（next.config.js）

```js
{ source: '/api/mybot/:path*', destination: 'https://bot.dlogicai.in/api/mybot/:path*' }
```

---

## フロントエンド構成（Next.js）

```
src/app/
├── page.tsx                       → 既存TOPページ（変更なし）
├── chat/page.tsx                  → 既存チャット（変更なし）
├── mybot/
│   ├── page.tsx                   → ① LP
│   ├── create/
│   │   └── page.tsx               → ② MYBOT作成・編集
│   └── [userId]/
│       └── page.tsx               → ④ MYBOTチャット
│
src/components/mybot/
├── HeroSection.tsx                → LP ヒーロー
├── FeatureSection.tsx             → LP 機能説明
├── PresetShowcase.tsx             → LP プリセット紹介
├── StepSection.tsx                → LP 3ステップ
├── CTASection.tsx                 → LP CTA
├── BotProfileForm.tsx             → BOT名・性格・口調・アイコン
├── IMLogicWeightEditor.tsx        → 12項目設定（既存IMLogicSettings.tsx移植）
├── PublishToggle.tsx              → 公開/非公開
├── SettingsHistory.tsx            → 編集履歴 + 復元
├── MybotChatInterface.tsx         → MYBOTチャットUI（既存chat UI流用）
│
src/hooks/
├── useMybotSettings.ts            → MYBOT設定CRUD
├── useMybotChat.ts                → MYBOTチャットSSE（既存useChat流用）
│
src/services/
├── mybotService.ts                → MYBOT API通信
```

---

## 実装フェーズ

### Phase 1-A: バックエンド（VPS Flask + Supabase）
1. Supabaseテーブル作成（`mybot_settings`, `mybot_settings_history`）
2. Flask MYBOT設定API実装（`/api/mybot/settings` CRUD + 履歴 + 復元）
3. アイコンアップロードAPI（Supabase Storage）
4. MYBOTチャットAPI（既存chat APIの拡張、IMLogicウェイト注入）
5. BOTプロフィールをsystem promptに注入するロジック

### Phase 1-B: フロントエンド（Next.js）
1. next.config.js に `/api/mybot/*` proxy追加
2. MYBOT作成ページ（`IMLogicSettings.tsx` 移植 + BOTプロフィールフォーム + 履歴UI）
3. MYBOTチャットページ（既存ChatUI流用 + BOTプロフィール表示 + IMLogic結果）
4. LP（`/mybot`）
5. LINE認証ガード（既存 `useLineAuth` 流用）

### Phase 2: 成績・公開・コミュニティ
1. 予想結果記録 + 的中率・回収率計算
2. みんなのBOTページ（`/mybot/explore`）
3. BOTランキング（回収率順）
4. 他ユーザーBOTの購読・利用機能
5. 既存 `IMLogicCommunityList.tsx` 等のコミュニティUIを参考に構築
