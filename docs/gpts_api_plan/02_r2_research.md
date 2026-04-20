# DlogicAI R2バケット調査レポート

作成日: 2026-04-21
調査範囲: `E:\dev\Cusor\dlogic-agent`, `E:\dev\Cusor\chatbot\uma\backend`
制約: コード変更なし・機密値は非表示・R2には直接アクセスしない

> **⚠️ セキュリティ重要所見(冒頭で要通知)**
> R2のアクセスキーID / シークレットキーが **ソースコードに平文ハードコーディング** されていました(複数ファイルに複数世代の鍵)。詳細は §1・§7 参照。GPTs公開APIを作る作業の前後どちらでもよいので、早めに鍵のローテーションを推奨します。値は本レポートでは一切表示しません。

---

## 1. R2認証情報の管理状態

### 1.1 管理方式の判定

| 方式 | 利用有無 |
|---|---|
| `.env` / `.env.local` / `.env.production` に格納 | **❌ 使われていない**(`.env` 内を grep しても R2 系キーは見つからず) |
| ソースコード内に平文ハードコード | **⚠️ これ**(Pythonスクリプト・bashスクリプトに直書き) |
| `docker-compose.yml` / `Dockerfile` での `env_file` 参照 | **見つからない**(両リポジトリにDocker定義自体なし) |
| GitHub Actions secrets 参照 | **見つからない**(`.github/workflows/` 不在) |
| systemd サービスファイルの `EnvironmentFile=` | **不明**(systemd unit ファイルはVPS側にあり、ローカルリポジトリに含まれない) |

### 1.2 キー名の存在確認(値は非表示)

探したキー名の有無:

| 探索キー名 | 存在 | 備考 |
|---|---|---|
| `R2_ACCESS_KEY_ID` | ❌ (標準名は未使用) | 代わりに `R2_ACCESS_KEY` / `ACCESS_KEY` が定義 |
| `R2_SECRET_ACCESS_KEY` | ❌ (標準名は未使用) | 代わりに `R2_SECRET_KEY` / `SECRET_KEY` が定義 |
| `R2_ACCOUNT_ID` / `CLOUDFLARE_ACCOUNT_ID` | ❌ 明示的な変数なし | ただしエンドポイントURLに account ID が埋め込まれている |
| `R2_BUCKET_NAME` / `R2_BUCKET` | ✅ ソース内ハードコード | 値は `dlogic-knowledge-files` (これは機密ではないのでレポート記載) |
| `R2_ENDPOINT` / `R2_ENDPOINT_URL` | ✅ ソース内ハードコード | S3互換エンドポイント(account ID含有のため値は非表示) |
| `R2_PUBLIC_URL` | ✅ ソース内ハードコード | `pub-xxxxxxxx.r2.dev` 形式(§5で詳述) |
| `R2_CUSTOM_DOMAIN` | ❌ | カスタムドメイン設定はコード上には **無し** |
| `CLOUDFLARE_API_TOKEN` / `CF_API_TOKEN` | ❌ | R2用のS3キーのみ。Cloudflare本体のAPIトークンはコード上に見当たらず |

### 1.3 ハードコードされているファイル(鍵の値は表示せず、場所のみ)

| ファイル | 行 | 鍵世代 |
|---|---|---|
| `chatbot/uma/backend/scripts/weekly_knowledge_update.py` | 33〜37 | 世代A |
| `dlogic-agent/scripts/daily_prefetch.py` | 34〜38 | 世代A(同じ値と思われる) |
| `chatbot/uma/backend/scripts/simple_upload.py` | 18〜22 | 世代B(2025-10-06更新コメント付き) |
| `chatbot/uma/backend/scripts/upload_r2.sh` | 4〜6 | 世代B |
| `chatbot/uma/backend/scripts/upload_r2_curl.sh` | 5〜7 | 世代C(末尾に「APIトークンを無効化してください」注記あり) |
| `chatbot/uma/backend/scripts/upload_to_r2_api.py`, `upload_via_cloudflare_api.py`, `upload_with_new_api.py`, `upload_to_cloudflare.py`, `simple_upload_*.py` など | 複数 | 内容未展開だがファイル名から類推で同様 |

3世代以上の異なる鍵ペアが残置。過去の鍵が有効か失効済みかは**不明**。

---

## 2. アップロード処理の詳細

### 2.1 メインのアップロード経路(2系統)

| 経路 | スケジュール | 実行ファイル | 対象 |
|---|---|---|---|
| **週次ナレッジ更新** | 毎週月曜12:00 JST(Windowsタスクスケジューラ) | `chatbot/uma/backend/scripts/weekly_knowledge_update.py` | JRA/NAR 馬・騎手ナレッジ 4ファイル |
| **日次プリフェッチ** | 毎日(時刻 **不明**) | `dlogic-agent/scripts/daily_prefetch.py` | 翌日のレースエントリ(`prefetch/` プレフィックス) |

タスクスケジューラ登録/手動実行のバッチ:
- `chatbot/uma/backend/scripts/setup_weekly_task.bat` — タスク登録(管理者実行)
- `chatbot/uma/backend/scripts/run_weekly_update.bat` — 手動実行

### 2.2 使用ライブラリ

| ライブラリ | 使用箇所 |
|---|---|
| **boto3** (+ botocore) | `weekly_knowledge_update.py`, `daily_prefetch.py` の `upload_to_r2()` 関数 |
| **requests** (自作AWS SigV4) | `simple_upload.py` 系 — boto3なしで署名を手実装している |
| **curl + --aws-sigv4** | `upload_r2.sh` — curlの組み込みAWS認証を利用 |
| **curl + 手動SigV4** | `upload_r2_curl.sh` — シェルで署名計算 |

`requirements.txt` レベルでは `boto3` は宣言されていない可能性(dlogic-agentの requirements.txt には含まれず)。週次バッチ実行時にだけローカル環境で動く運用と推定。

### 2.3 バケット・キー命名規則

週次更新のタスク定義(`weekly_knowledge_update.py` L44〜73):

| 生成スクリプト | 出力ファイル名 | R2キー(日付付き) | R2キー(latest) |
|---|---|---|---|
| `create_jra_knowledge_v2.py` | `jra_knowledge_quality_{YYYYMMDD}.json` | 同名 | `jra_knowledge_latest.json` |
| `create_jra_jockey_knowledge.py` | `jra_jockey_knowledge_{YYYYMMDD}.json` | 同名 | `jra_jockey_knowledge_latest.json` |
| `create_all_nar_knowledge.py` | `all_nar_unified_knowledge_{YYYYMMDD}.json` | 同名 | `all_nar_unified_knowledge_latest.json` |
| `create_all_nar_jockey_knowledge.py` | `all_nar_jockey_knowledge_{YYYYMMDD}.json` | 同名 | `all_nar_jockey_knowledge_latest.json` |

日次プリフェッチ(`daily_prefetch.py` L108〜127): `prefetch/<ファイル名>` のプレフィックス付き。

バケット: **`dlogic-knowledge-files`** (両経路とも共通)。

### 2.4 VPS同期の副作用

`weekly_knowledge_update.py` L155〜210: R2アップロードの後、**CDN URLを含むservices系Pythonファイル6本をVPSにSCP同期し、`systemctl restart dlogic-backend` を叩く** フローが続きます。

同期対象:
- `dlogic_raw_data_manager.py`
- `jockey_data_manager.py`
- `local_dlogic_raw_data_manager_v2.py`
- `local_jockey_data_manager.py`
- `local_imlogic_engine.py`
- `local_fast_dlogic_engine.py`

つまり「R2へPUT → services系の `cdn_url = "..."` 参照先を最新化 → VPSキャッシュ削除 → バックエンド再起動」までが1コマンドで完結する設計。

---

## 3. 読み込み処理の詳細

### 3.1 アクセス方式

**公開 `pub-xxxxxxxx.r2.dev` URLに対して `requests.get()` でHTTP GET**。
S3互換APIも署名付きURLも使っていません。= **バケットはPublic Access有効**。

各 services 側(`chatbot/uma/backend/services/*.py`)で `cdn_url = "https://pub-059afaafefa84116b57d57e0a72b81bd.r2.dev/..."` としてハードコードされ、そのまま GET → JSON.loadsしてインメモリに保持。

### 3.2 ローカルキャッシュ

あり。`dlogic_raw_data_manager.py` L135〜146 等で `self.knowledge_file` パスにダウンロード結果を書き出し。Render環境(旧デプロイ先)では `/var/data/`、それ以外はサービス定義の `knowledge_file` パス。VPS環境では `/opt/dlogic/backend/data/*.json` と推定(週次バッチの再起動シーケンスで削除している)。

### 3.3 読み込み対象の一覧(services/ grep結果)

| services/ のファイル | cdn_url |
|---|---|
| `dlogic_raw_data_manager.py` | `jra_knowledge_latest.json` |
| `jockey_data_manager.py` | `jra_jockey_knowledge_latest.json` |
| `local_dlogic_raw_data_manager.py` | `nankan_unified_knowledge_20250907.json` (日付固定) |
| `local_dlogic_raw_data_manager_v2.py` | `all_nar_unified_knowledge_latest.json` |
| `local_jockey_data_manager.py` | `all_nar_jockey_knowledge_latest.json` |
| `local_imlogic_engine.py` | `all_nar_unified_knowledge_latest.json` + `all_nar_jockey_knowledge_latest.json` |
| `local_fast_dlogic_engine.py` | `all_nar_unified_knowledge_latest.json` |
| `extended_knowledge_manager.py` | `unified_knowledge_20250903.json` (日付固定) |
| `dlogic_lazy_data_manager.py` | 同上 |
| `viewlogic_data_manager.py` | 同上 |
| `jockey_knowledge_manager.py` | `jockey_knowledge.json` |
| `knowledge_selector.py` | モード別に5種類(下記) |
| `emergency_switch.py` | 緊急切替用の別系統 |
| `modern_dlogic_engine.py` | エラーメッセージ内に `dlogic_extended_knowledge.json` URL |

`knowledge_selector.py` の参照先(nankan vs legacy切替):
- `dlogic_raw_knowledge.json`
- `dlogic_extended_knowledge.json`
- `viewlogic_knowledge.json`
- `jockey_knowledge.json`
- `nankan_unified_knowledge_20250907.json`
- `unified_knowledge_20250903.json`

---

## 4. R2バケット内容の推定リスト

実際のバケット一覧は取得していません。コードに登場するキー名から推定:

| 推定R2キー | 推定サイズ | 更新頻度 | 備考 |
|---|---|---|---|
| `jra_knowledge_latest.json` | ~300MB(dlogic_raw_knowledgeの後継と思われる) | 週次月曜 | **エイリアス**(正式にオーバーライト) |
| `jra_knowledge_quality_{YYYYMMDD}.json` | 同上 | 週次月曜 | 履歴保存 |
| `jra_jockey_knowledge_latest.json` | 数MB | 週次月曜 | エイリアス |
| `jra_jockey_knowledge_{YYYYMMDD}.json` | 数MB | 週次月曜 | 履歴保存 |
| `all_nar_unified_knowledge_latest.json` | サイズ **不明** | 週次月曜 | エイリアス |
| `all_nar_unified_knowledge_{YYYYMMDD}.json` | 同上 | 週次月曜 | 履歴保存 |
| `all_nar_jockey_knowledge_latest.json` | 数MB | 週次月曜 | エイリアス |
| `all_nar_jockey_knowledge_{YYYYMMDD}.json` | 数MB | 週次月曜 | 履歴保存 |
| `dlogic_raw_knowledge.json` | ~292MB | 過去の固定ファイル(レガシー参照) | `knowledge_selector.py` のlegacy経路 |
| `dlogic_extended_knowledge.json` | ~193MB | 同上 | レガシー経路 |
| `viewlogic_knowledge.json` | **不明** | 同上 | レガシー経路 |
| `jockey_knowledge.json` | **不明** | 同上 | レガシー経路 |
| `unified_knowledge_20250903.json` | **不明**(ローカルから確認不可) | 2025-09-03 固定 | extended_knowledge_manager 他が参照 |
| `nankan_unified_knowledge_20250907.json` | 数MB〜 | 2025-09-07 固定 | 南関東専用 |
| `prefetch/races_{YYYYMMDD}.json` 等 | 数百KB | 日次 | ビューア用(admin画面から閲覧) |

### エイリアス運用

`*_latest.json` は **4種類すべてで併用**(上記の現行4ファイル)。週次バッチが日付付き版を上げた直後に同一内容で `_latest.json` も上書きする方式。

### .gz圧縮版

アップロード処理には `.gz` の記述は **見当たらない**(`ContentType='application/json'` のみ)。ローカル生成物には `.json.gz` が存在するがR2に上がっているかは**不明**(上がっていない可能性が高い)。

---

## 5. 公開設定の現状

### 5.1 判定: **パブリック(public-read 有効)**

根拠:
- バックエンド services 群が `https://pub-059afaafefa84116b57d57e0a72b81bd.r2.dev/<key>` を **認証なしの `requests.get()`** で叩いてJSONを取得している
- エラー時に「CDN URL: https://pub-...r2.dev/...」とそのままユーザ向けログに出す設計
- Shellスクリプトでも同URLを「公開URL」として出力

これはR2の「Public Access → r2.dev subdomain を Allow」を有効化した状態そのもの。

### 5.2 カスタムドメイン

コード内に `knowledge.dlogicai.in` のようなカスタムドメイン記述は **見つからない**。現状は `pub-059afaafefa84116b57d57e0a72b81bd.r2.dev` のCloudflare発行サブドメインを直接利用。

### 5.3 CORS・ヘッダ操作

- アップロード時に `ContentType='application/json'` を付与するのみ
- `Cache-Control` / `x-amz-meta-*` 等の明示的ヘッダ操作は**見当たらない**
- CORS設定の手がかりは**ソース側には無し**(R2ダッシュボード側で設定されている可能性あり、**不明**)

### 5.4 署名付きURL

**使われていない**。presign呼び出し(`generate_presigned_url`, `boto3 ... sign`)は検索してもヒットせず。公開バケットで運用しているため不要な設計。

---

## 6. Workers構築に向けた前提条件チェック

| 項目 | 判定 | コメント |
|---|---|---|
| R2バケットへのAPIアクセス権(S3互換キー) | **○** | 複数世代の有効そうなキーがソース内に存在。ただし要ローテ |
| R2内のファイル構造の把握 | **○** | 命名規則・エイリアス運用が`weekly_knowledge_update.py`で明文化 |
| ナレッジファイルのスキーマ文書化 | **△** | `JRA_knowledge_structure_report.md`, `NAR_KNOWLEDGE_COMPLETE_GUIDE.md` 等のMDが存在。ただし最新スキーマとの整合は**不明** |
| Cloudflareダッシュボードへの管理アクセス | **不明** | コード側には管理APIトークンなし。仁さんのCloudflareアカウントで要確認 |
| wrangler CLI のインストール | **×**(今回の調査環境) | `wrangler` コマンドがPATHに無い(exit 127)。他プロジェクト(`line/apps/worker`, `starfish`, `tensei/cloudflare/*`)には `wrangler.toml` あり、**別環境でのインストール経験はあり** |

---

## 7. GPTs API構築までのギャップ分析

### 7.1 技術的に必要な準備(実装前)

1. **R2キーのローテーション**(最優先)
   - ソースに平文で3世代の鍵が残っている。コミット履歴を遡ればさらに流出の可能性
   - Cloudflareダッシュボードで全既存キーを無効化 → 新規発行
   - 新キーは `.env.local` / `secrets manager` に移し、コード側は `os.getenv()` 経由に書き換え(※コード変更が必要なので今回は実施しない)

2. **Cloudflare API Tokenの発行**(wrangler/Workers用)
   - 現状は **S3互換キーのみ**。Workers デプロイや Workers KV 操作には Cloudflare本体の API Token が別途必要
   - 発行スコープ例: `Account - Workers Scripts:Edit`, `Account - Workers KV Storage:Edit`, `Account - R2:Edit`

3. **Workers プロジェクトの初期化**
   - 新規ディレクトリ(例 `E:\dev\Cusor\dlogic-public-api\`)で `npm create cloudflare@latest` → `wrangler.toml` 生成
   - R2バケット `dlogic-knowledge-files` を `[[r2_buckets]]` でバインド
   - Workers KV を作成してレート制限カウンタ用にバインド

4. **キャッシュ戦略の選定**
   - Workers → R2 直接読み出しは GB級JSONを毎回ロードすると重い
   - 選択肢: (a) R2側でIndexだけ別JSONに切出、(b) Workers Cache API で TTL短め、(c) Workers KVに小分けして保存、(d) D1に再投入
   - 大元のJSONは数百MBなので、**「GPTsに返すサブセットだけ別キーで生成・配信」** が現実的

5. **OpenAPI 3.1 スキーマ作成**
   - GPTs Custom Actions用の yaml/json
   - 1エンドポイント10行程度

### 7.2 仁さんがCloudflareダッシュボードで確認/設定すべきこと

1. **R2バケット `dlogic-knowledge-files` の現状確認**
   - Public Access → r2.dev subdomain が "Allowed" になっているか(コードから推定ではYes)
   - 現在のオブジェクト数とサイズ合計
   - カスタムドメイン(Custom Domain)未設定かどうか
   - CORSポリシーの現状(Headers → CORS Policy 欄)

2. **R2 APIトークンの整理**
   - Account → R2 → Manage R2 API Tokens で発行済み一覧を確認
   - ソースに残っている鍵を失効
   - 新規トークンを「読み取り専用」「書き込み専用」で分ける(GPTsへの配信は読取のみ)

3. **Workers プラン確認**
   - Free: 1日10万リクエスト / 10msCPU — GPTs想定トラフィックなら十分
   - Paid($5/月): 1日1000万リクエスト — スケール時のみ

4. **Workers KV の作成**
   - レート制限カウンタ用(1日5回/IP制限)
   - 名前例: `DLOGIC_PUBLIC_RATELIMIT`

5. **カスタムドメイン設計**(任意)
   - `api.dlogicai.in` / `public.dlogicai.in` / `knowledge.dlogicai.in` のどれを使うか
   - Workers Route か Custom Domain かの選択
   - DNS(dlogicai.in のネームサーバ)がCloudflare管理下にあるか確認

### 7.3 開発環境で事前にインストール/設定すべきツール

| ツール | 推奨バージョン | 用途 |
|---|---|---|
| Node.js | ≥ 20 LTS | wrangler の動作要件 |
| wrangler CLI | 最新 | `npm install -g wrangler` or `npx wrangler` |
| Cloudflare アカウント認証 | - | `wrangler login` (ブラウザOAuth) |
| (任意) `rclone` | 最新 | R2バケット内容の一覧・diff確認が楽 |
| (任意) Cloudflare公式VSCode拡張 | - | `wrangler.toml` 補完 |

---

## 8. サンプルJSON構造の再確認(R2キー名の対応)

前回の調査で扱ったファイルを、**R2上で実際に使われているキー名**にマッピング:

| 前回レポートで触れたローカルファイル | R2でのキー(推定) | 備考 |
|---|---|---|
| `extended_jockey_knowledge.json`(ローカル10MB) | **R2には直接の同名キーは無し**。`jra_jockey_knowledge_latest.json` が後継と推定 | 週次更新対象 |
| `dlogic_extended_knowledge.json`(ローカル193MB) | `dlogic_extended_knowledge.json`(レガシー経路、日付固定) + `jra_knowledge_latest.json`(現行) | `knowledge_selector.py` のモード切替で使い分け |
| `dlogic_raw_knowledge.json`(ローカル292MB) | `dlogic_raw_knowledge.json`(レガシー固定) + `jra_knowledge_latest.json`(現行後継) | 実質 `jra_knowledge_latest.json` が現役 |
| `jockey_knowledge.json` (想定) | `jockey_knowledge.json`(レガシー固定) + `jra_jockey_knowledge_latest.json`(現行) | 同上 |
| `nar_schedule_master_2020_2026.json`(dlogic-agent配下) | **R2にはアップロードされていない可能性が高い**(コード検索で該当なし) | ローカル/VPSのみで利用 |

### GPTs API候補として推奨できるR2キー

| 優先度 | R2キー | 理由 |
|---|---|---|
| **高** | `jra_jockey_knowledge_latest.json` | 騎手×コース統計、自社集計価値・サイズ(数MB)ともに外部配信向き |
| **高** | `all_nar_jockey_knowledge_latest.json` | NAR騎手版、同じ理由 |
| 中 | `prefetch/races_{YYYYMMDD}.json` | 出馬表の公開情報、サイズも小さい |
| 低 | `jra_knowledge_latest.json` (大型) | 300MB級でGPTsから直接取得は非現実的。Worker側でサブセット抽出が必須 |
| 低 | `all_nar_unified_knowledge_latest.json` (大型) | 同上 |

### 各ファイルの中身スキーマ

前回レポート §2.3 で扱ったサンプル構造と同じと推定(週次バッチのスクリプト実装を読まないと確定不可のため **不明**):
- 馬ナレッジ系: `{ "馬名": [走歴配列] }`
- 騎手ナレッジ系: `{ "騎手名": { "venue_course_stats": { "会場_距離": {stats} } } }`

---

## 付記: まとめ表

| 観点 | 現状 |
|---|---|
| R2バケット名 | `dlogic-knowledge-files` |
| 公開状態 | **Public**(r2.devサブドメインで認証なしアクセス可) |
| 認証情報の保管 | **ソースに平文ハードコード(要ローテ)** |
| アップロード自動化 | ✅ 週次月曜12:00 + 日次プリフェッチ |
| エイリアス運用 | ✅ `*_latest.json` で4種類 |
| カスタムドメイン | ❌ 未設定 |
| CORS設定 | **不明**(ダッシュボード確認要) |
| Workers配備実績 | 無し(dlogic-agent/chatbot-uma-backend 内) |
| Workers実績(他プロジェクト) | あり(`line/apps/worker`, `starfish`, `tensei/cloudflare/*`) |
| API Token(Cloudflare本体用) | 無し(コード検索結果) |
| wrangler CLI(今マシン) | 未インストール |

### 推奨される作業順序(高レベル)

1. R2キーのローテーション + 環境変数化(本レポート §7.1)
2. Cloudflareダッシュボードで現バケット状態確認(§7.2)
3. 新規Workersプロジェクト雛形作成(別ディレクトリで)
4. `wrangler.toml` に R2バインド + KVバインド
5. GPTs向けの軽量サブセットJSONを別R2キーで生成するバッチを追加(例: `public/jockey_index.json`)
6. Workers がそのサブセットを読み、slowapi 相当のレート制限を KV カウンタで実装
7. OpenAPI 3.1 スキーマでGPTs Custom Actionsに登録
