# 🚨 VPS障害・復旧ハンドオフ (2026-06-03)

> **新しいClaudeへ**: これは進行中のインシデント引き継ぎ書です。まずこれを全部読んでから動いてください。
> 状況が変わったら**このファイルを更新**して次のセッションに引き継ぐこと。

## 一行サマリー
**料金未払いでXserver VPS (220.158.24.157) が解約 → 本番(LINE Bot/予想backend)が全停止中。Xserverサポートにデータ復元を問い合わせ済み、回答待ち（最後のチャンス）。** 週次ナレッジ更新のknowledge生成+R2は完了済み、VPS依存3段階だけ未完。

## 現在のステータス（2026-06-03 朝時点）
- **待機中**: Xserverサポートへ「データ復元可否・完全削除期限」を問い合わせ済み。jinさんが回答を待っている。
- 支払いボタンは消失済み（＝契約解除フェーズ。利用停止ではない）。データ復旧は期待薄だが復元できれば最速。
- **本番影響**: VPS全ポート(22/80/443/5000/8000)無応答 = VPSダウン。
  - 停止中: dlogic-linebot(:5000, 本番), dlogic-backend(:8000, 予想エンジン), dlogic-telegram
  - 生存: 公開サイト dlogicai.in（別ホスティング, HTTP 200）, Cloudflare R2, Supabase
- 切り分け済み: traceroute は上流 103.54.156.27(Xserver系) まで到達しVPS本体のみ無応答 → ネットワーク経路ではなくVPS消滅。

## 🔴 停止中サービス（VPS 220.158.24.157 = `/opt/dlogic/` 全体）
当初「LINE Botだけ」と思っていたが、**競馬関連スタック全部**がこの1台に同居していた。再構築は全部が対象。
| ディレクトリ | サービス | ポート/公開 | ローカル元 |
|---|---|---|---|
| `linebot/` | LINE Bot本番 | :5000 / `bot.dlogicai.in/callback` 等 | `dlogic-agent`（このリポジトリ, git） |
| `backend/` | 予想エンジン FastAPI | :8000 / `bot.dlogicai.in/api` | `uma/backend`（git, ただし main_lite消失） |
| `netkeita-api/` | 記事/予想API | :5002 / `bot.dlogicai.in/nk` | `E:\dev\Cusor\netkeita\api\`（git, **SCP直接運用**） |
| `tornado/` | トルネードAI | ? | 要確認（[[project_tornado_ai]]） |
| `odds-monitor/` | オッズ監視 | ? | 要確認 |
| `note/` | 危険人気馬BOT | (4/26から停止中) | `/opt/dlogic/note/`（VPSのみ?要確認） |
| cron | 日次プリフェッチ/穴党・GANTZ配信/bet-results | — | `dlogic-agent/scripts/` 各種 |
| systemd | dlogic-linebot/backend/telegram, netkeita-api, push-gantz, update-bet-results | — | 一部再作成済(下記) |

**別サーバー（生存）**: OpenClaw VPS `210.131.222.240`（別契約）。ただし記事生成cronはdlogic VPSへSSHする構成のため実質停止。dlogicai.in本体（別ホスティング）は表示のみ生存。

## 失われていない資産（復旧の土台）
| 資産 | 場所 | 状態 |
|---|---|---|
| ナレッジ4種 | Cloudflare R2 (`dlogic-knowledge-files`) | ✅ 2026-06-03生成・`_latest`配信中 |
| ユーザーデータ | Supabase (外部) | ✅ 無傷 |
| LINE Bot本番コード | `E:\dev\Cusor\dlogic-agent\`(このリポジトリ+git) | ✅ |
| backend api/v2 + services | `E:\dev\Cusor\chatbot\uma\backend\` | ✅（大部分） |
| nginx設定 | `dlogic-agent/scripts/nginx_dlogic.conf` | ✅ |
| cron | `dlogic-agent/scripts/setup_vps_cron.sh` + `vps_cron_{jra,nar,results}.py` | ✅ |
| 環境変数 | `dlogic-agent/.env.local`, `uma/backend/.env` | ✅ |

## ⚠️ ローカルに無い／要確認（VPSにしか無かった可能性 = 復元で埋まる部分）
1. ~~**systemdユニット3本**~~ → ✅ **2026-06-03 再作成済み**: `scripts/dlogic-{linebot,backend,telegram}.service`（gunicorn_conf.py / main.py / CLAUDE.md から復元）。
2. **backend エントリポイント `main_lite.py`** → 🔴 **消失確定**。ローカル・git履歴・起動痕跡のいずれにも無し（CLAUDE.md内の言及のみ）。母体は `uma/backend/main.py`（734行フル版, `uvicorn main:app :8000`, race_analysis_v2等router内包）。`main_simple.py`(59行)は最小版。再構築では main.py を使い不要routerを絞って "lite" 化する（runbook手順3参照）。
3. VPS側 `.env.local`（/opt/dlogic/linebot/.env.local）、VPS Redis中身（レースレベル/セッション）、prefetch/response_cache。

## 📦 待機中に用意した再構築アセット（2026-06-03）
- `scripts/dlogic-linebot.service` … gunicorn+gevent 8worker :5000（app:app）
- `scripts/dlogic-backend.service` … uvicorn main:app :8000（※実機は main_lite、復元時は戻す）
- `scripts/dlogic-telegram.service` … python main.py（polling, 管理者用）
- `docs/VPS_REBUILD_RUNBOOK.md` … 新Ubuntu VPSへのゼロからフル再構築手順（DNS/TLS/cron/Redis/新IP再設定込み）
- **重要な簡略化**: 本番は `bot.dlogicai.in`(Certbot TLS)経由。**新VPSでもDNS A を新IPへ向け直すだけでLINE webhook URL `https://bot.dlogicai.in/callback` は変更不要**。

## 今日の週次更新の結果（参考: project_weekly_knowledge メモリ参照）
- ✅ ナレッジ4種生成 + R2(dated + `_latest`)アップロード完了。HTTP HEADで実体確認済み。
  - jra_knowledge_quality 534.3MB / jra_jockey 141.9MB / all_nar_unified 350.1MB / all_nar_jockey 441.6MB
- ✅ `race_level_20260603.json`(6.9MB) ローカル生成済み（`E:\dev\Cusor\netkeita\scripts\`）
- ❌ **未完（VPS復旧後に補完が必要な3段階）**:
  1. JRAレースレベルを VPS Redis(db=3, key `nk:racelevel:*`, TTL1年) へ投入
  2. サービスファイル6本を `/opt/dlogic/backend/services/` へSCP同期
  3. backend ローカルキャッシュ削除 + `systemctl restart dlogic-backend`
- 注意: knowledge再生成は不要（R2済み）。再構築でもbackendが `_latest` を読むので新サーバーでも自動反映。

## 分岐A: Xserverがデータ復元できた場合
1. VPS起動・SSH疎通確認: `ssh root@220.158.24.157 "hostname; systemctl status dlogic-linebot dlogic-backend dlogic-telegram"`
2. 週次の残り3段階を補完（手動 or `uma/backend/scripts/weekly_knowledge_update.py` の VPS段階のみ再実行）。
3. LINE webhook疎通・予想動作を確認。

## 分岐B: 復元できなかった場合（新VPSへ再構築）
1. 新VPS(Ubuntu)契約 → 新IP取得。
2. ローカルに無い穴を埋める: `main_lite.py` 捜索、systemdユニット3本を再作成しリポジトリ保存。
3. フルデプロイ:
   - linebot: `dlogic-agent` 一式を `/opt/dlogic/linebot/` へ、venv作成、`requirements.txt`、gunicorn+gevent、systemd `dlogic-linebot`(:5000)
   - backend: `uma/backend` を `/opt/dlogic/backend/`、systemd `dlogic-backend`(:8000)
   - telegram: systemd `dlogic-telegram`(polling)
   - nginx(`scripts/nginx_dlogic.conf`) + TLS、cron(`setup_vps_cron.sh`)
   - `.env.local` 配置（APIキーはローカルにあり）
   - Redis導入 → レースレベル再投入（`race_level_*.json`）
4. **新IPに伴う再設定**: LINE Developers の webhook URL、DNS、CLAUDE.md/メモリのIP更新。
5. 動作確認。

## 重要な技術メモ（週次更新の再発防止 / Windows運用）
- 週次更新リポジトリは別: `E:\dev\Cusor\chatbot\uma\backend\`、オーケストレーター `scripts/weekly_knowledge_update.py`。
- **使うPython = Store版3.12**: `C:\Users\USER\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe`（= `py -3.12`）。`uma/backend/venv` は壊れたWSL venvで使用不可。
- **プロセス名は `python3.12.exe`**（`python.exe` ではない）。二重起動チェック/killは `Name -like 'python3.12*'` か `CommandLine -like '*weekly_knowledge*'` で。`python.exe` で探すと取りこぼし→全DEAD誤判定→多重起動（2026-06-03に実際発生、収束済み）。
- 起動は **実コンソール(`-WindowStyle Minimized`、リダイレクト無し)**。Hidden+stdout/stderrリダイレクトだとStore pythonの子subprocess spawnが失敗し親ごと無言終了。進捗は `uma/backend/logs/weekly_update_YYYYMMDD.log` をtailで監視。
- 無関係な常駐 python3.12（5/28起動の8772/30312等）を巻き込まないこと。

## 参照
- プロジェクト全体: `CLAUDE.md`（VPS構成・systemd・デプロイ手順）
- メモリ: `project_weekly_knowledge`, `project_status`, `feedback_windows_python_ops`, `reference_netkeita_vps`, `reference_openclaw_vps`
- VPS旧情報: IP 220.158.24.157 / root / `/opt/dlogic/{linebot,backend}`

---
_最終更新: 2026-06-03（Xserver回答待ちで待機中）。状況更新時はこのファイルとメモリ `project_vps_outage_20260603` を更新すること。_
