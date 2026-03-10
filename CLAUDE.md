# CLAUDE.md - Dlogic Agent (競馬AIチャットボット)

## プロジェクト概要
競馬予想AIエージェント「ディーロジ」。Telegram Bot + LINE Bot で動作。
Claude API (Haiku 4.5) の Tool Use でデータ取得・予想エンジン呼び出しを行うエージェント型チャットボット。

## 重要な戦略方針
- **Dlogicサイトのチャット機能は廃止予定** → LINE Bot一本化
- **Telegram版は管理者（jin）テスト用** として残す
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
    ├── app.py            # 統合エントリポイント (LINE + Telegram)
    ├── config.py         # 設定・システムプロンプト
    ├── agent/engine.py   # Claude API呼び出し・ツール通知ヘルパー
    ├── bot/handlers.py   # Telegram Bot ハンドラー (async agentic loop)
    ├── bot/line_handlers.py  # LINE Bot ハンドラー (sync agentic loop)
    ├── tools/definitions.py  # Claude Tool Use定義
    ├── tools/executor.py     # ツール実行 + レースデータキャッシュ
    ├── scrapers/             # netkeiba.comスクレイピング
    ├── memory/               # ユーザーメモリJSON
    ├── .env.local            # 環境変数 (API keys)
    └── venv/                 # Python 3.13 venv
```

## systemdサービス
```bash
# Bot (LINE + Telegram) — port 5000
systemctl restart dlogic-linebot
systemctl status dlogic-linebot
journalctl -u dlogic-linebot -f

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
scp bot/handlers.py root@220.158.24.157:/opt/dlogic/linebot/bot/handlers.py

# 3. サービス再起動
ssh root@220.158.24.157 "systemctl restart dlogic-linebot"

# 4. ログ確認
ssh root@220.158.24.157 "journalctl -u dlogic-linebot --since '1 min ago' --no-pager"
```

## アーキテクチャ
```
ユーザー → Telegram/LINE → app.py → handlers.py (agentic loop)
                                        ↓
                                    Claude API (Haiku 4.5, Tool Use)
                                        ↓ tool_use
                                    executor.py → スクレイピング or API呼び出し
                                        ↓                          ↓
                                  netkeiba.com              VPS backend:8000
                                  (出馬表,オッズ等)          (予想エンジン,展開分析)
```

### agentic loop の流れ
1. ユーザーメッセージ受信
2. Claude API呼び出し (Tool Use付き)
3. stop_reason == "tool_use" → ツール実行 → 結果をhistoryに追加 → 2に戻る
4. stop_reason == "end_turn" → 最終テキストをユーザーに返信
5. 各ツール実行前に通知メッセージ送信 ("⚡ エンジン起動中...")

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

## 既知の課題・注意事項
- Haiku は出馬表を省略する傾向がある → system promptで「全頭表示」を厳命
- Haiku は「確度」等の禁止語を使いがち → 禁止語リストで対処中
- サービス再起動時に Telegram 409 Conflict が出るが一時的 (数秒で解消)
- ポート8000が残ることがある → backend serviceに ExecStartPre で fuser -k 追加済み
- レースデータキャッシュ (_race_cache) はインメモリ → サービス再起動でクリア

## Phase 2 予定 (未着手)
- Supabaseへのユーザー管理移行
- ポイント制導入
- メモリの永続化 (JSON → Supabase DB)

## ローカル環境変数 (.env.local)
```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=8620232885:...
DLOGIC_API_URL=http://localhost:8000
CLAUDE_MODEL=claude-haiku-4-5
LINE_CHANNEL_SECRET=...
LINE_CHANNEL_ACCESS_TOKEN=...
```
