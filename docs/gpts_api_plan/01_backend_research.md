# DlogicAI バックエンド調査レポート(GPTs API開放向け)

作成日: 2026-04-21
調査範囲: `E:\dev\Cusor\dlogic-agent`(LINE Bot層), `E:\dev\Cusor\chatbot\uma\backend`(予想エンジン層)
調査方針: コード変更なし・機密情報非表示・不明は明記

---

## 1. プロジェクト概要

### 1.1 リポジトリが2つに分かれている

調査の結果、「DlogicAIバックエンド」は **2つのPythonプロジェクトを合わせた構成** であることが判明しました。どちらもVPS(Xserver `220.158.24.157`)に常駐するsystemdサービス。

| 役割 | ローカルパス | VPSデプロイ先 | ポート |
|---|---|---|---|
| **LINE Bot / WebChat / MYBOT / Data API** | `E:\dev\Cusor\dlogic-agent` | `/opt/dlogic/linebot/` | 5000 |
| **予想エンジン(FastAPI)** | `E:\dev\Cusor\chatbot\uma\backend` | `/opt/dlogic/backend/` | 8000 |
| ナレッジ更新パイプライン | `E:\dev\Cusor\chatbot\uma\backend` (兼用) | (ローカル実行 → R2アップロード) | - |

LINE Bot層がClaude Tool Useのagentic loopを担当し、予想計算が必要になると内部HTTPで FastAPI層を呼び出す構造。

### 1.2 ディレクトリ構成 (dlogic-agent, 深さ3まで)

```
E:\dev\Cusor\dlogic-agent
├── agent/              # Claude/OpenAIエージェントロジック
│   ├── chat_core.py
│   ├── engine.py       # Tool Use agentic loop
│   ├── mybot_chat.py
│   ├── response_cache.py
│   └── template_router.py
├── api/                # Flask blueprints (HTTP endpoints)
│   ├── auth.py         # LINE Login / JWT
│   ├── data_api.py     # ⭐ 最も外部公開向きなRESTラッパ
│   ├── mybot.py
│   ├── user.py
│   ├── web_chat.py
│   └── v2/
│       └── imlogic_prediction.py (※FastAPI的に書かれているが未ロード)
├── bot/                # LINE / Telegram handlers
│   ├── handlers.py
│   ├── line_handlers.py
│   ├── mybot_line_handler.py
│   └── tone_messages.py
├── db/                 # Supabase / Redis クライアント
│   ├── supabase_client.py
│   ├── user_manager.py
│   ├── prediction_manager.py
│   ├── redis_client.py
│   ├── engine_stats.py
│   ├── encryption.py
│   └── result_manager.py
├── scrapers/           # netkeiba.com スクレイピング
│   ├── jra.py / nar.py / archive.py / horse.py
│   ├── odds.py / race_result.py / horse_weight.py
│   └── stable_comment.py / training_comment.py / validators.py
├── tools/
│   ├── definitions.py  # 20個のClaude Tool定義
│   └── executor.py     # ツール実行ブリッジ
├── scripts/            # cron/バッチ (prefetch, 結果取得, rich menu等)
├── data/
│   ├── prefetch/       # 日次プリフェッチJSON (3ファイル/304KB)
│   ├── cache/          # レスポンスキャッシュ (実体はVPS側)
│   └── nar_schedule_master_2020_2026.json
├── app.py              # Flask エントリ (Gunicorn用)
├── main.py             # Telegram Bot エントリ
├── config.py
├── gunicorn_conf.py
└── supabase_setup.sql
```

### 1.3 技術スタック

| レイヤ | 使用技術 |
|---|---|
| 言語 | Python 3.13 |
| HTTPフレームワーク | Flask 3.x (+ flask-cors) / FastAPI (backend側) |
| WSGIサーバ | Gunicorn + gevent (2〜8 workers) |
| LLM | Anthropic Claude Haiku 4.5 (メイン) / OpenAI互換差替可 |
| LINE SDK | linebot-sdk v3 |
| DB | Supabase (PostgreSQL + Auth) |
| キャッシュ | Redis (セッション/履歴) + ファイルキャッシュ |
| スクレイピング | requests + BeautifulSoup + lxml |
| レート制限 | slowapi (backend側) + 自作 `api/v2/rate_limiter.py` |
| ホスティング | **VPS (Xserver, 220.158.24.157)** — systemd管理 |
| CDN | **Cloudflare R2** (ナレッジファイル配信) |

### 1.4 Cloudflare 関連ファイル

| 調査項目 | 結果 |
|---|---|
| `wrangler.toml` / `wrangler.jsonc` | **見つからなかった**(`E:\dev\Cusor` 配下全域を検索) |
| Cloudflare Workers のソース | **見つからなかった** |
| Cloudflare R2 の利用 | **あり**(バケット名 `dlogic-knowledge-files`) |

重要: **現状Cloudflare Workersは使われていません**。仁さんの質問前提「現在Cloudflare Workersで動いているAPI」は今のシステムには該当しません。APIは全てVPS上のPython(Flask/FastAPI)で動作しています。R2はあくまでナレッジJSONの静的配信CDNとしてのみ使用。

---

## 2. ナレッジデータの現状

### 2.1 ナレッジファイルの配置場所

| 場所 | 役割 | 備考 |
|---|---|---|
| `E:\dev\Cusor\chatbot\uma\backend\data\` | **マスター(ローカル生成)** | 開発マシンで毎週月曜12:00に生成 |
| Cloudflare R2 `dlogic-knowledge-files` | **配信CDN** | backend側は `*_latest.json` を参照 |
| `/opt/dlogic/backend/` (VPS) | 実行時にR2からDL or ローカルコピー | 詳細は **不明**(要VPS確認) |
| `E:\dev\Cusor\dlogic-agent\data\prefetch\` | レース出馬表の日次プリフェッチ | 3ファイル / 304KB(極小) |

### 2.2 ファイル形式・件数・容量

`E:\dev\Cusor\chatbot\uma\backend\data\` 配下の `*knowledge*.json` を集計:

- **ファイル形式**: JSON(一部 `.gz` 圧縮版が併存)
- **ファイル数**: 約142個(ビルド中の途中生成物を含む)
- **総容量**: 数GB以上と推定(下記代表ファイルから逆算)
- **圧縮配信**: `.json.gz` 版も同梱(R2配信時の転送量削減用と推定)

#### 代表的な大型ファイル(サイズ順)

| ファイル | サイズ | 内容 |
|---|---|---|
| `dlogic_raw_knowledge.json` | **292MB** | JRA全馬の過去走レコード(JRA-VAN準拠フィールド) |
| `dlogic_raw_knowledge_backup_20250906.json` | 281MB | 上記のバックアップ |
| `dlogic_extended_knowledge.json` | **193MB** | 拡張版(DLogicスコア計算済み指標) |
| `extended_jockey_knowledge.json` | **10MB** | 騎手×会場×距離の勝率/複勝率 |
| `jockey_knowledge_YYYYMMDD.json` | 数MB | 週次更新の騎手ナレッジ |
| `2024_jra_g1_races.json` / `2024_real_g1_races.json` | 小 | G1レースメタデータ |

`data/chunks/dlogic_raw_knowledge_chunk_01.json` のようなチャンク分割版も存在(配信用分割と推定)。

### 2.3 サンプル内容(3種類)

#### (a) `dlogic_extended_knowledge.json` — 馬別の過去走レコード

```json
{
  "マイネルグスタフ": [
    {
      "BAMEI": "マイネルグスタフ",
      "RACE_CODE": "2023071507030512",
      "KAISAI_NEN": "2023",
      "KAISAI_GAPPI": "0715",
      "KAKUTEI_CHAKUJUN": "13",
      "TANSHO_ODDS": "1536",
      "TANSHO_NINKIJUN": "14",
      "KISHUMEI_RYAKUSHO": "幸英明　",
      "CHOKYOSHIMEI_RYAKUSHO": "吉田直弘",
      "KYORI": "1200",
      "TRACK_CODE": "23",
      ...
    }
  ]
}
```

- **粒度**: 馬名キー → 過去走配列
- **フィールド**: JRA-VANデータラボの正規カラム名(KAKUTEI_CHAKUJUN=確定着順、KYORI=距離、等)

#### (b) `extended_jockey_knowledge.json` — 騎手×コース別成績

```json
{
  "Ｃ．デム": {
    "venue_course_stats": {
      "中山_2000": {"races": 1, "wins": 0, "top3": 0, "win_rate": 0.0, "top3_rate": 0.0},
      "中山_2500": {"races": 2, "wins": 0, "top3": 1, "win_rate": 0.0, "top3_rate": 0.5},
      "中山_1800": {"races": 1, "wins": 1, "top3": 1, "win_rate": 1.0, "top3_rate": 1.0}
    }
  }
}
```

- **粒度**: 騎手名 → `{会場_距離: 成績}` の辞書
- 展開系エンジン(`get_jockey_analysis`)がこの構造をそのまま返す

#### (c) `nar_schedule_master_2020_2026.json` — 地方競馬カレンダー

```json
{
  "metadata": {
    "period": "2020-01-01 to 2026-12-31",
    "total_race_days": 2279,
    "venues": {"83": "帯広", "30": "門別", "35": "盛岡", ...}
  }
}
```

- **粒度**: 日付×会場のスケジュールマスタ

### 2.4 粒度まとめ

| データ種別 | 粒度 | ファイル例 |
|---|---|---|
| 馬別過去走 | 馬名 → 走歴配列 | `dlogic_raw_knowledge.json` |
| 騎手×コース | 騎手 → `{会場_距離}` | `extended_jockey_knowledge.json` |
| 血統×コース | 父/母父 → `{会場_距離}` | (関連ファイル **不明** — backend services層に埋め込み可能性) |
| レース別 | レースコード → エントリ | `2024_jra_g1_races.json` |
| 会場別 | NAR会場コードマスタ | `nar_schedule_master_2020_2026.json` |
| 週次更新 | 日付付き + `*_latest` エイリアス | `jra_knowledge_quality_YYYYMMDD.json` 他計4種 |

---

## 3. 既存API構造

### 3.1 Flask層(LINE Bot / WebChat / MYBOT, port 5000)

#### 認証不要・公開向け候補 (`/api/data/*`)

`E:\dev\Cusor\dlogic-agent\api\data_api.py` で Blueprint登録:

| Method | Path | 役割 | 認証 |
|---|---|---|---|
| GET | `/api/data/races` | レース一覧(日付+JRA/NARフィルタ) | **なし** |
| GET | `/api/data/entries/<race_id>` | 出馬表 | **なし** |
| GET | `/api/data/odds/<race_id>` | リアルタイム単勝オッズ | **なし** |

コメント曰く「dlogic-note等の外部プロジェクトに提供する用」。**GPTs開放にはこの層が最も近い形**。

#### 認証あり(LINEログイン or JWT)

| Path | 役割 |
|---|---|
| `/callback` | LINE Bot webhook(署名検証) |
| `/mybot/webhook/<user_id>` | MYBOT webhook |
| `/api/chatauth/line`, `/liff`, `/me`, `/link`, `/link-request` | LINE Login JWT発行/検証 |
| `/api/mybot/*` (約15エンドポイント) | MYBOTの設定/公開/チャット |
| `/api/chat`, `/api/chat/sessions`, `/api/chat/health` | WebChat UI向け |
| `/api/user/profile`, `/upload-icon`, `/stats` | ユーザープロフィール |

認証方式: `Authorization: Bearer <token>` — トークンは `HMAC-SHA256(WEB_AUTH_SECRET)` の自作署名(`api/auth.py`)。有効期限7日。

#### 管理用

| Path | 認証 |
|---|---|
| `/health` | なし |
| `/x/{ADMIN_SECRET}/races/<date>` | URLに秘密文字列埋め込み(推測困難URL方式) |

### 3.2 FastAPI層(予想エンジン, port 8000)

`E:\dev\Cusor\chatbot\uma\backend\main.py` + `api/*.py` + `api/v2/*.py`

#### 主要エンドポイント(抜粋)

LINE Botが内部から叩いている想定のエンジンAPI:

| Path | 役割 |
|---|---|
| `/api/v2/analysis/race-flow` | 展開予想(ViewLogic) |
| `/api/v2/analysis/jockey-analysis` | 騎手分析 |
| `/api/v2/analysis/bloodline-analysis` | 血統分析 |
| `/api/v2/analysis/recent-runs` | 直近5走 |
| `/api/v2/predictions/newspaper` | 4エンジン一括予想 |
| `/api/v2/dlogic/batch` | Dlogic複数馬バッチ |
| `/api/v2/dlogic/precalculate` | 事前計算 |
| `/api/v2/imlogic/*` | ユーザーカスタム重みづけ予想 |
| `/api/v2/points/*` | ポイント管理 |
| `/api/v2/chat/*` | v2 チャットセッション |
| `/api/v2/health/`, `/ready`, `/stats` | ヘルスチェック |
| `/api/admin/knowledge-update/{secret_key}` | ナレッジ月次更新トリガ |
| `/api/admin/batch-dlogic-analyze` | バッチ分析 |
| `/api/archive-races/search` | 過去レース検索 |
| `/fast-dlogic/horse-analysis`, `/race-analysis` | 高速版 |

**合計エンドポイント数は概算で70以上**(全カタログ化は未実施)。

#### 認証方式

| パターン | 使用場所 |
|---|---|
| **認証なし** | `/api/data/*` (Flask)、`/api/v2/predictions/newspaper` (明示的に「認証不要」とコメント)、`/api/v2/health/*`、`/api/v2/analysis/*` の一部 |
| **Bearer JWT(自作HMAC)** | Flask `/api/chatauth/*`, `/api/mybot/*`, `/api/user/*` |
| **Clerk JWT** | backend `api/v2/auth.py` で `CLERK_JWKS_URL` 検証(フロントエンド向け) |
| **Supabase service_role** | `db/supabase_client.py` 経由で内部から直接DB操作 |
| **秘密キー(URL埋め込み)** | `/api/admin/knowledge-update/{secret_key}`, `/x/{ADMIN_SECRET}/races` |

### 3.3 レート制限

| 場所 | 設定 |
|---|---|
| `backend/main.py` | slowapi `Limiter(key_func=get_remote_address, default_limits=["100 per minute"])` — **IPベース、全エンドポイント既定100/分** |
| `backend/api/v2/rate_limiter.py` | 自作 `RateLimiter`クラス、**ユーザーID**ベース。設定値: chat_message=30/分, settings_save=10/分, session_create=5/分, default=60/分 |
| `dlogic-agent` (Flask層) | **明示的なレート制限なし**(Gunicorn+geventの同時接続上限のみ) |

---

## 4. データアクセスロジック

### 4.1 ナレッジ読み込み担当ファイル

| ファイル | 役割 |
|---|---|
| `backend/services/knowledge_base.py` | (推定)汎用ナレッジローダ — `main.py` で import |
| `backend/services/enhanced_knowledge_base.py` | DLogic拡張版 — `api/d_logic.py` で使用 |
| `backend/services/dlogic_raw_data_manager.py` | 生データ管理 — `api/v2/dlogic.py` で使用 |
| `backend/services/integrated_d_logic_calculator.py` | 12項目スコア計算 |
| `backend/services/viewlogic_engine.py` / `local_viewlogic_engine_v2.py` | 展開予想エンジン(JRA/NAR切替) |
| `backend/services/redis_cache.py` | Redisキャッシュ統合 |
| `backend/services/monthly_knowledge_updater.py` | ナレッジ月次更新 |
| `dlogic-agent/tools/executor.py` | ツール実行ブリッジ(backend APIをHTTP呼出) |

注: `services/` 配下は実ファイルを読んでいないため関数詳細は **不明**。名前からの推測。

### 4.2 主要な検索・取得関数(判明分)

| 関数 | 所在 | 役割 |
|---|---|---|
| `DLogicEngine.calculate_d_logic_score(horse, conditions)` | `api/d_logic.py:19〜` | 12項目(距離適性/血統/騎手/調教師/馬場/天候/人気/斤量/馬体重/コーナー/着差/…)を計算し `DLogicScore` を返す |
| `_build_race_data(req)` | `api/v2/viewlogic_analysis.py:27〜` | リクエスト → ViewLogicエンジンへ渡すrace_data辞書に整形 |
| `_get_engine(venue)` | 同上:55〜 | JRA会場なら `ViewLogicEngine`、NAR会場なら `LocalViewLogicEngineV2` を切り替えて返す |
| `_get_today_races(params)` / `_get_race_entries(params)` / `_resolve_netkeiba_race_id(...)` | `dlogic-agent/tools/executor.py` | プリフェッチJSON → アーカイブ → スクレイピングの優先順位で解決 |
| `fetch_realtime_odds`, `fetch_race_result`, `fetch_horse_weights`, `fetch_training_comments`, `search_horse`, `fetch_comments_for_race` | `dlogic-agent/scrapers/*` | netkeiba.com スクレイパー群 |
| `_query_engine_stats` | `db/engine_stats.py` | エンジン別的中率をSupabaseから取得 |

### 4.3 Supabase スキーマ概要

`supabase_setup.sql` + `scripts/create_*.sql` + `scripts/migrate_*.sql` から判明:

| テーブル | 主キー | 用途 |
|---|---|---|
| `user_profiles` | `id` (UUID) | LINEユーザープロフィール(favorite_venues/horses/jockeys, bet_style, risk_level等の構造化項目) |
| `user_memories` | `id` (UUID) | 会話から抽出した記憶(category, content) |
| `prediction_history` | `id` (UUID) | 予想リクエスト履歴(将来のポイント基盤) |
| `login_history` | (参照のみ) | IP/UA/user_id のログイン記録 |
| `engine_hit_rates` | 参照のみ | エンジン別的中率(`create_engine_hit_rates.sql`) |
| `race_results` | 参照のみ | レース確定結果(`create_prediction_tables.sql`) |
| `mybot_stats` | 参照のみ | MYBOT統計(`migrate_mybot_stats.sql`) |
| `mybot_public`関連 | 参照のみ | MYBOT公開設定(`migrate_mybot_public.sql`) |

RLSは全テーブルで有効化されるが、**サーバは service_role キーで操作するため実質RLSは無視される**(`supabase_setup.sql` のコメント明記)。

---

## 5. GPTs API開放に向けた論点

### 5.1 どのナレッジを開放すれば本業を食わないか

「本業サービス」= LINE Bot(ディーロジ) + WebChat(dlogicai.in) + dlogic-note + (将来)トルネードAI、と理解しています。

| データ種別 | 開放リスク | コメント |
|---|---|---|
| 馬別過去走(`dlogic_raw_knowledge.json`) | **中〜高** | JRA-VAN正規データの集約物。再配布ポリシー要確認(JRAの利用規約違反の恐れ **不明**) |
| 騎手×コース成績 | **低** | 自社集計済みの統計値で独自付加価値。GPTsで引けても対話体験・UI・速報性で差別化可 |
| 血統×コース成績 | **低** | 同上 |
| 予想結果(Dlogic/Ilogic/ViewLogic/MetaLogic) | **高** | 本業の中核機能。レート制限かければ「味見」で開放可だが、無制限は危険 |
| 展開予想(race-flow) | **中** | 本業機能だが大量データは出にくく、1レース1応答なので制限しやすい |
| リアルタイムオッズ | **低(自社計算ではない)** | netkeibaスクレイプを転送しているだけ。公開するならnetkeiba規約のチェック必要 |
| レース一覧・出馬表 | **低** | 公開情報の再配布 |

**推奨の開放範囲**(仁さんが決めるべきポイント):
1. レース一覧 / 出馬表 / 騎手・血統サマリのみ、予想は出さない → リード獲得ツールとして
2. 予想も1日数回だけ → 「試食モデル」、本命の精度を実感させてLINE誘導
3. 全部開放 → ブランド拡張するが、本業のLINE会員が減るリスク

### 5.2 レート制限 1日5回/ユーザー の実装方法

前提: GPTsのCustom Actionsは通常 `X-OpenAI-Ecosystem-Id` と `X-Openai-Conversation-Id` ヘッダが付与されるが、**安定したユーザー識別子の提供はGPTsの仕様上限定的**(執筆時点、要確認)。

選択肢:

| 方式 | 長所 | 短所 |
|---|---|---|
| **IPベース**(`slowapi` 既存パターン) | 実装2時間以内。`Limiter(key_func=get_remote_address, default_limits=["5 per 1 day"])` を専用blueprint or routerに付与するだけ | NATや共有回線で誤検知。BOT回避も容易 |
| **GPTs発行のAPIキーを1日5回使い捨て配布** | ユーザー単位で正確に制限可 | 配布システムの構築が必要。摩擦が大きい |
| **Cloudflare Turnstile + IP + UA複合** | 多少堅牢化 | GPTs経由のheadless呼出で挑戦されやすい |
| **Redisカウンタ(バックエンド既設の `db/redis_client.py`)を流用** | 既存Redisに `key=gpts:<identifier>:<YYYYMMDD>` で `INCR` + `EXPIRE`。実装は既存パターンに沿う | IPベースと同じく識別子の精度に依存 |

**推奨**: slowapi + Redis(backendに既設)の組合せ。実装目安はエンドポイント1つあたり 0.5〜1日(テスト含む)。

### 5.3 Cloudflare Workers 上での新規エンドポイント追加工数

**大前提の修正**: 現状Workersは存在しません。選択肢は2つ:

**選択肢A**: 既存のFastAPI(VPS上)に `/public/v1/*` プレフィックスのルータを1本追加
- 工数目安: **1〜2日**
- 作業: 新blueprint作成 → 既存 `services/knowledge_base.py` を再利用 → slowapi適用 → nginx(推定)で `/public/v1/*` を公開
- 利点: 既存実装資産を100%流用
- 注意: **jinさんに確認が必要** — 公開APIを既存の2800人ユーザー向けインフラに同居させてよいか

**選択肢B**: 新規にCloudflare Workers + R2 + Workers KVで軽量ラッパを作る
- 工数目安: **3〜5日**
- 作業: wrangler初期化 → R2のナレッジJSONを読むWorker実装 → Workers KVでレート制限カウンタ → カスタムドメイン設定
- 利点: 本業インフラと完全分離、スケーラビリティ、DDoS耐性
- 欠点: 予想計算(Python依存)がWorkersでは動かないので、**複雑なエンドポイントは結局VPSへプロキシ**する二段構え

**推奨**: まずAから始め、GPTsからのトラフィックが予想を超えて跳ねたらBへ移行、という段階戦略。

### 5.4 既存認証システムとの分離(公開APIは認証なしにしたい)

既存認証の棲み分け:

| エンドポイント群 | 認証 |
|---|---|
| `/api/chatauth/*`, `/api/user/*`, `/api/mybot/*` | JWT(自作HMAC) — 利用者のLINEアカウントに紐づく |
| `/api/v2/chat/*`, `/api/v2/points/*` 等 | Clerk JWT — フロント(dlogicai.in)利用者向け |
| `/api/data/*` (既存) | **既に認証なし** — dlogic-noteから呼び出し用 |
| 予定: `/public/v1/*` (新規) | **認証なし** + レート制限 |

**分離方法**(コード変更提案・未実装):
1. 新Blueprint/Routerを独立ファイル(例 `api/public.py` or `backend/api/v2/public.py`)に作る
2. 既存の `verify_auth_header()` や Clerk検証ミドルウェアを**一切importしない**
3. nginxで `/public/v1/*` のみ別ログファイル・別レート制限ゾーンに隔離
4. CORSは `allow_origins=["*"]` で開放(既存の厳格なオリジン制限を継承しない)
5. 異常トラフィック時に即切れるよう、nginx or Cloudflare側にkill-switch用のmaintenance modeを用意

既存認証との衝突リスクは低いですが、**同じslowapi Limiterインスタンスを共有すると既存ユーザーの枠を公開APIが食いつぶす危険**があるので、Limiterも分離すべきです。

---

## 6. 推奨する次のアクション

優先順位つきで提案します。仁さんの意思決定ポイントを太字にしました。

1. **【今日中に判断】開放範囲の決定**
   - 「レース一覧・出馬表」のみ? 「+騎手・血統サマリ」? 「+予想(日5回制限)」?
   - これでエンドポイント設計の8割が決まります

2. **【今日中に調査】netkeiba / JRA-VANデータの再配布規約確認**
   - `dlogic_raw_knowledge.json` はJRA-VAN由来の可能性が高く、GPTs経由の外部配信が規約違反かどうか **不明**
   - 仁さんが過去の利用規約書類を持っているなら確認、なければ法務/JRA-VANに問合せ

3. **【1〜2日】FastAPI側に `/public/v1/*` プロトタイプを追加**
   - 選択肢A(既存FastAPI拡張)で先行着手
   - 最初は `/public/v1/races`, `/public/v1/entries/{id}`, `/public/v1/jockey/{name}` の3本だけ
   - slowapi で `5 per 1 day` をIPベースに付与

4. **【1日】GPTsのCustom Action用OpenAPIスペック作成**
   - 上記3エンドポイントのOpenAPI 3.1 YAMLを書いてGPTsに登録
   - GPTsでエンドユーザー識別ヘッダが取れるか実機確認(ドキュメントだけでは **不明**)

5. **【初回リリース後1週間】ログ監視 → Workers移行の要否判断**
   - 想定外のトラフィックなら選択肢B(Cloudflare Workers移行)に進む
   - 既存R2バケット `dlogic-knowledge-files` がそのまま使えるので移行は比較的楽

6. **【随時】Droid(factory-droid)にアーキ監査を依頼**
   - CLAUDE.md方針: 公開APIの追加はスケーラビリティ・コスト・セキュリティに関わるので、Droidの目を通す価値あり

---

## 付記: 不明点リスト

コード変更なしの調査では確定できなかった項目を明示します:

- VPS上 `/opt/dlogic/backend/` の実際のナレッジファイル配置(ローカル直置き/R2 DL/S3互換マウント)
- `services/knowledge_base.py` 等の内部関数シグネチャ(ファイル本体は未読)
- Cloudflare R2 バケットへの公開アクセス可否・CORS設定
- JRA-VAN / netkeiba 再配布の利用規約抵触範囲
- GPTs Custom Actions の執筆時点での認証ヘッダ仕様
- backend側の実エンドポイント総数(概算70+、全カタログは未実施)
- 血統×コース統計ファイルの具体的な場所(backend services内の可能性)
