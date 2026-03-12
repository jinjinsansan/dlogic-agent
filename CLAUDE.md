# CLAUDE.md - Dlogic Agent (競馬AIチャットボット)

## プロジェクト概要
競馬予想AIエージェント「ディーロジ」。LINE Bot (本番) + Telegram Bot (管理者テスト用) で動作。
Claude API (Haiku 4.5) の Tool Use でデータ取得・予想エンジン呼び出しを行うエージェント型チャットボット。

## 重要な戦略方針
- **Dlogicサイトのチャット機能は廃止予定** → LINE Bot一本化
- **Telegram版は管理者（jin）テスト用** として残す（別サービスで稼働）
- LINE Botが本番プロダクト
- 旧Render デプロイは廃止 → **VPS (Xserver) に完全移行済み**

## VPS接続情報
- **IP**: 220.158.24.157
- **ユーザー**: root
- **SSH**: `ssh root@220.158.24.157`
- **SCP**: `scp ファイル root@220.158.24.157:/opt/dlogic/linebot/`

## VPSディレクトリ構成
```
/opt/dlogic/
├── backend/              # FastAPI予想エンジンバックエンド (port 8000)
│   ├── main_lite.py      # エントリポイント
│   └── api/v2/
│       └── viewlogic_analysis.py  # 展開系4エンドポイント
│
└── linebot/              # ⭐ このプロジェクトのデプロイ先 (port 5000)
    ├── app.py            # LINE Bot エントリポイント (Gunicorn用)
    ├── main.py           # Telegram Bot エントリポイント (別サービス)
    ├── gunicorn_conf.py  # Gunicorn設定 (gevent, 8ワーカー)
    ├── config.py         # 設定・システムプロンプト
    ├── agent/engine.py   # Claude API呼び出し・ツール通知ヘルパー
    ├── agent/response_cache.py  # レスポンスキャッシュ (ファイルベース)
    ├── bot/handlers.py   # Telegram Bot ハンドラー (async agentic loop)
    ├── bot/line_handlers.py  # LINE Bot ハンドラー (sync agentic loop)
    ├── db/supabase_client.py  # Supabase client (singleton)
    ├── db/user_manager.py     # ユーザー管理 CRUD (Supabase)
    ├── tools/definitions.py  # Claude Tool Use定義
    ├── tools/executor.py     # ツール実行 + レースデータキャッシュ
    ├── scripts/warm_cache.py     # レスポンスキャッシュウォーミング
    ├── scripts/daily_prefetch.py # 日次レースデータ自動プリフェッチ
    ├── scrapers/             # netkeiba.comスクレイピング
    ├── data/cache/           # レスポンスキャッシュ (JSON)
    ├── data/prefetch/        # プリフェッチデータ (JSON)
    ├── .env.local            # 環境変数 (API keys)
    └── venv/                 # Python 3.13 venv
```

## systemdサービス
```bash
# LINE Bot (Gunicorn + gevent, 8ワーカー) — port 5000
systemctl restart dlogic-linebot
systemctl status dlogic-linebot
journalctl -u dlogic-linebot -f

# Telegram Bot (管理者テスト用, polling) — 別サービス
systemctl restart dlogic-telegram
systemctl status dlogic-telegram
journalctl -u dlogic-telegram -f

# Backend (FastAPI予想エンジン) — port 8000
systemctl restart dlogic-backend
systemctl status dlogic-backend
journalctl -u dlogic-backend -f
```

## デプロイ手順 (GitHubなし、直接SCP)
```bash
# 1. ローカルで編集
# 2. VPSへファイル転送
scp config.py root@220.158.24.157:/opt/dlogic/linebot/config.py
scp bot/line_handlers.py root@220.158.24.157:/opt/dlogic/linebot/bot/line_handlers.py

# 3. サービス再起動
ssh root@220.158.24.157 "systemctl restart dlogic-linebot"

# 4. ログ確認
ssh root@220.158.24.157 "journalctl -u dlogic-linebot --since '1 min ago' --no-pager"
```

## アーキテクチャ
```
ユーザー → LINE → Gunicorn (8 gevent workers) → line_handlers.py
                                                     ↓
                                             レスポンスキャッシュ確認
                                            (ファイルベース, 全ワーカー共有)
                                                ↓ miss
                                            Claude API (Haiku 4.5, Tool Use)
                                                ↓ tool_use
                                            executor.py → スクレイピング or API
                                                ↓                    ↓
                                          netkeiba.com        VPS backend:8000
                                                ↓
                                        レスポンスキャッシュ保存
                                        (次のユーザーは即返し)
```

### agentic loop の流れ
1. ユーザーメッセージ受信
2. レスポンスキャッシュ確認 → ヒットなら即返し ($0)
3. Claude API呼び出し (Tool Use付き, プロンプトキャッシュ有効)
4. stop_reason == "tool_use" → ツール実行 → 結果をhistoryに追加 → 3に戻る
5. stop_reason == "end_turn" → 最終テキストをユーザーに返信
6. レスポンスキャッシュ保存 + メモリ抽出
7. 各ツール実行前に通知メッセージ送信 ("⚡ エンジン起動中...")

### ツール一覧
| ツール名 | 用途 | データソース |
|---|---|---|
| get_today_races | 今日のレース一覧 | TSアーカイブ → スクレイピング |
| get_race_entries | 出馬表取得 | TSアーカイブ → スクレイピング |
| get_predictions | 4エンジン予想 | VPS backend API |
| get_realtime_odds | リアルタイムオッズ | スクレイピング |
| search_horse | 馬データ検索 | スクレイピング |
| get_race_flow | 展開予想 | VPS backend API |
| get_jockey_analysis | 騎手分析 | VPS backend API |
| get_bloodline_analysis | 血統分析 | VPS backend API |
| get_recent_runs | 直近5走 | VPS backend API |

## コスト最適化
- **プロンプトキャッシュ**: システムプロンプトに cache_control 付与 → 90%削減
- **レスポンスキャッシュ**: 同じレースの回答は全ユーザー共有 → ファイルベース、全ワーカー共有
- **日次ウォーミング**: daily_prefetch.py → warm_cache.py で事前にキャッシュ生成

## スケーラビリティ
- **Gunicorn + gevent**: 8ワーカー × 200接続 = 1,600同時接続対応
- **レスポンスキャッシュ**: 500人同時でも最初の1人以外は即返し
- **Supabase**: ユーザー管理の永続化、スケール無制限

## ユーザー管理 (Phase 2 完了)
- **Supabase**: user_profiles, user_memories, prediction_history テーブル
- **LINE Bot**: Supabase経由でユーザー管理・メモリ保存
- **Telegram Bot**: JSON memory (管理者テスト用のため簡易)
- 構造化プロフィール: favorite_venues, bet_style, risk_level 等

## 既知の課題・注意事項
- Haiku は出馬表を省略する傾向がある → system promptで「全頭表示」を厳命
- Haiku は「確度」等の禁止語を使いがち → 禁止語リストで対処中
- レースデータキャッシュ (_race_cache) はインメモリ → サービス再起動でクリア
- レスポンスキャッシュ (response_cache) はファイルベース → 再起動しても残る

## ローカル環境変数 (.env.local)
```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=8620232885:...
DLOGIC_API_URL=http://localhost:8000
CLAUDE_MODEL=claude-haiku-4-5
LINE_CHANNEL_SECRET=...
LINE_CHANNEL_ACCESS_TOKEN=...
SUPABASE_URL=https://agkuvhiycthrloxzhgjc.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...
```
