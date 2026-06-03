# VPS フル再構築 runbook (新Ubuntu VPSへゼロから)

> 作成: 2026-06-03（Xserver VPS解約インシデント対応）。背景は `VPS_INCIDENT_20260603.md`。
> **Xserverからデータ復元できた場合はこの手順は不要**。復元NGで新VPSに建て直す場合に使う。
> 旧VPS: 220.158.24.157 / Ubuntu / root。port 5000(linebot) 8000(backend)。

## 確定方針（2026-06-03 jin決定）
- プロバイダ: **Xserver VPS 再契約** / スペック: **8 vCPU・16GB** / OS: Ubuntu
- 進め方: **本番優先で段階復旧**
  - **Stage 1（最優先）**: LINE Bot(:5000) + backend予想(:8000) → 本番復活
  - **Stage 2**: netkeita-api(:5002, `/nk`) + 記事系（OpenClaw cronの向き先もこのVPS）
  - **Stage 3**: tornado(トルネードAI) + odds-monitor(オッズ監視)
- 契約時の必須事項: **支払い自動更新ON / 残高アラート設定**（今回の未払い再発防止）、SSH公開鍵登録（下記）、新IP控え

### サービス別ローカルソース（全部揃っている）
| サービス | VPS配置 | ローカル | git |
|---|---|---|---|
| LINE Bot | `/opt/dlogic/linebot/` | `E:\dev\Cusor\dlogic-agent\` | ✓ |
| backend | `/opt/dlogic/backend/` | `E:\dev\Cusor\chatbot\uma\backend\` | ✓(main_lite除く) |
| netkeita-api | `/opt/dlogic/netkeita-api/` | `E:\dev\Cusor\netkeita\api\` | ✓(SCP運用) |
| tornado | `/opt/dlogic/tornado/` | `E:\dev\Cusor\tornado-ai\`(+`tornado-ai-frontend`) | ✓ |
| odds-monitor | `/opt/dlogic/odds-monitor/` | `E:\dev\Cusor\dlogic-odds-monitor\` | ✓ |

### SSH鍵（新VPSに登録 → このPCからscp/sshデプロイ可能に）
登録する公開鍵（どちらか／両方）:
- `~/.ssh/id_ed25519.pub` = `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEQYSnSarmPVgKGK0SgBn0vWBWw06BjQwoHjlmsRzOIA USER@DESKTOP-UH30MN6`
- `~/.ssh/xserver_key.pub`（旧Xserver用の専用鍵。Xserver再契約なら流用しやすい）

## 0. 前提・準備するもの（すべてローカルにある）
- LINE Bot一式: `E:\dev\Cusor\dlogic-agent\`（このリポジトリ）
- backend一式: `E:\dev\Cusor\chatbot\uma\backend\`
- nginx: `dlogic-agent/scripts/nginx_dlogic.conf`
- systemdユニット: `dlogic-agent/scripts/dlogic-{linebot,backend,telegram}.service`（2026-06-03再作成）
- cron: `dlogic-agent/scripts/setup_vps_cron.sh`, `vps_cron_{jra,nar,results}.py`
- 環境変数: `dlogic-agent/.env.local`, `uma/backend/.env`
- ナレッジ: Cloudflare R2（`_latest` 配信中、再生成不要）
- レースレベル: `E:\dev\Cusor\netkeita\scripts\race_level_20260603.json`

## 1. 新VPS契約・初期設定
1. 新VPS(Ubuntu 22.04+)契約 → **新IP**取得。SSH鍵登録 or rootパスワード。
2. `ssh root@<新IP>` 疎通確認。
3. 基本パッケージ:
   ```bash
   apt update && apt -y upgrade
   apt -y install python3-venv python3-pip nginx certbot python3-certbot-nginx redis-server git rsync
   systemctl enable --now redis-server
   mkdir -p /opt/dlogic/linebot /opt/dlogic/backend
   ```

## 2. LINE Bot (linebot, :5000) デプロイ
```bash
# ローカルから (PowerShell)。__pycache__/venv/data除外推奨
scp -r E:\dev\Cusor\dlogic-agent\* root@<新IP>:/opt/dlogic/linebot/
```
VPS側:
```bash
cd /opt/dlogic/linebot
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip install gunicorn gevent
# .env.local が配置されているか確認 (config.py が load_dotenv で読む)
ls -la .env.local
```

## 3. backend (予想エンジン, :8000) デプロイ
```bash
scp -r E:\dev\Cusor\chatbot\uma\backend\* root@<新IP>:/opt/dlogic/backend/
```
VPS側:
```bash
cd /opt/dlogic/backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # 無ければ fastapi uvicorn openai redis psycopg2-binary boto3 等を個別
ls -la .env
```
⚠️ **entrypoint注意**: VPS実機は `main_lite.py` だったが消失。`main.py`(フル版)が母体。
- まず `venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000` で起動確認。
- import失敗するrouterがあれば main.py 上部の `include_router`/import を必要分だけに絞る（= 元の "lite" 化）。
- linebotが叩くエンドポイント（get_predictions / get_race_flow / get_jockey_analysis / get_bloodline_analysis / get_recent_runs → `api/v2` 展開系含む）が生きているか確認。
- backend は R2 `_latest` からナレッジを読む実装なので、ナレッジ配置は不要（要確認: services/*_data_manager.py のCDN URL）。

## 4. systemd 登録（3サービス）
```bash
scp E:\dev\Cusor\dlogic-agent\scripts\dlogic-linebot.service  root@<新IP>:/etc/systemd/system/
scp E:\dev\Cusor\dlogic-agent\scripts\dlogic-backend.service  root@<新IP>:/etc/systemd/system/
scp E:\dev\Cusor\dlogic-agent\scripts\dlogic-telegram.service root@<新IP>:/etc/systemd/system/
ssh root@<新IP> "systemctl daemon-reload && systemctl enable --now dlogic-backend dlogic-linebot dlogic-telegram"
ssh root@<新IP> "systemctl status dlogic-backend dlogic-linebot dlogic-telegram --no-pager"
```
ローカル疎通: `curl http://127.0.0.1:8000/health` / `curl http://127.0.0.1:5000/health`

## 5. nginx + TLS
```bash
scp E:\dev\Cusor\dlogic-agent\scripts\nginx_dlogic.conf root@<新IP>:/etc/nginx/sites-available/dlogic
ssh root@<新IP> "ln -sf /etc/nginx/sites-available/dlogic /etc/nginx/sites-enabled/dlogic"
```
⚠️ 先に **DNS A レコード `bot.dlogicai.in` を新IPへ変更**（伝播待ち）。その後:
```bash
ssh root@<新IP> "certbot --nginx -d bot.dlogicai.in"   # 証明書を新規取得（conf内の旧証明書パスは上書きされる）
ssh root@<新IP> "nginx -t && systemctl reload nginx"
```

## 6. cron（日次プリフェッチ等）
```bash
scp E:\dev\Cusor\dlogic-agent\scripts\setup_vps_cron.sh root@<新IP>:/opt/dlogic/linebot/scripts/
ssh root@<新IP> "bash /opt/dlogic/linebot/scripts/setup_vps_cron.sh"
```

## 7. Redis レースレベル投入
```bash
scp E:\dev\Cusor\netkeita\scripts\race_level_20260603.json root@<新IP>:/tmp/jra_race_level.json
ssh root@<新IP> "python3 -c \"import json,redis; r=redis.Redis(host='127.0.0.1',port=6379,db=3,decode_responses=True); d=json.load(open('/tmp/jra_race_level.json',encoding='utf-8')); p=r.pipeline(transaction=False); [p.set(f'nk:racelevel:{k}', json.dumps(v,ensure_ascii=False), ex=86400*365) for k,v in d.items()]; p.execute(); print('Loaded', len(d))\""
```

## 8. 新IPに伴う再設定（重要）
- **DNS**: `bot.dlogicai.in` A → 新IP（手順5で実施済み）。
- **LINE webhook URL**: `https://bot.dlogicai.in/callback`。**ドメイン維持なら変更不要**（DNSが新IPを向けばOK）。LINE Developersで疎通(Verify)だけ確認。
- **CLAUDE.md / メモリ / .env系のIP**（220.158.24.157）を新IPへ更新。`reference_*` メモリも。
- 週次更新スクリプト `uma/backend/scripts/weekly_knowledge_update.py` の `VPS_HOST`、`vps_cron_*.py`、SCP系スクリプトのIPを新IPへ。

## 9. 最終確認
- `https://bot.dlogicai.in/health` が 200
- LINEで実際にメッセージ → 予想が返る
- backend展開系（騎手/血統/展開/過去走）が動く
- Telegram管理Botが応答
- 翌日の日次プリフェッチcronが動くか（ログ確認）

## 付録: ローカルに無く手動再現が要るもの
- `main_lite.py`（消失。main.py から再構成）
- VPS側 `.env.local`（/opt/dlogic/linebot 用。ローカル .env.local と内容差異があれば要確認）
- VPS Redis セッションデータ（揮発。再構築でクリアされるが実害小）
- response_cache / prefetch（再生成される）
