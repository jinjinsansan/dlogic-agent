# 金曜 6/5 やること (JRAオッズ実地確認ほか)

> 背景: 2026-06-03 にXserver VPS解約→新VPS(210.131.208.243)へ全サービス再構築。
> 詳細は `VPS_INCIDENT_20260603.md` / メモリ `project_vps_outage_20260603`。
> JRAオッズだけは平日に検証不能だったため、**前売りオッズが出る金曜(6/5)以降**に確認する。

## ★ 最優先: JRAオッズ(Lightpanda)実地確認

**なぜ金曜**: JRAオッズは前日(前売り)に公開。6/6(土)のオッズは6/5(金)に出る。平日はJRAレースが無く検証できなかった。

**現状(2026-06-03時点で確認済)**:
- Lightpanda(`/usr/local/bin/lightpanda`, v1.0.0-nightly)導入済、netkeiba shutubaページ描画OK、パーサ対象 `odds-1_N` span 存在(値は平日`---.-`)
- NARオッズは実値取得を検証済(動作OK)
- ⚠️ Lightpandaがオッズ取得JSを実行し値を埋めるかは**未確認**。Playwrightフォールバックは Ubuntu 26.04 非対応で**未導入**=Lightpandaがダメだと代替なし

### 確認手順 (VPSで実行)
```bash
ssh -i ~/.ssh/dlogic.pem root@210.131.208.243
cd /opt/dlogic/linebot

# 1. 6/6のJRA race_id を取得
venv/bin/python -c "import sys;sys.path.insert(0,'.');from scrapers.jra import fetch_race_list;rs=fetch_race_list('20260606');print(len(rs),'races');print([getattr(r,'race_id',None) for r in rs[:5]])"

# 2. 取得した race_id で実オッズが返るか (★これが本番確認)
venv/bin/python -c "import sys;sys.path.insert(0,'.');from scrapers.odds import fetch_realtime_odds;print(fetch_realtime_odds('<上で得たrace_id>','jra'))"
```

### 判定
- **非ゼロのオッズ dict が返る**(例 `{1: 3.2, 2: 8.1, ...}`)→ ✅ JRAオッズ復旧完了。何もしなくてよい(`dlogic-odds-refresh.timer` が09-22 JST/10分で自動更新)
- **`None` / `{}` / 全部0** → ❌ Lightpandaがオッズを取れていない。下記フォールバックへ

### フォールバック (上が失敗した場合)
Lightpandaがダメなら Playwright + chromium を入れる(Ubuntu 26.04でbundled chromiumが入らなかったので工夫が要る):
```bash
# 案1: apt版chromium + playwrightにchannel/executable_pathで指定
apt-get install -y chromium-browser   # or chromium
# scrapers/odds.py の _fetch_jra_odds_playwright を chromium executable_path 指定に改修してデプロイ
# 案2: playwright install chromium (--with-deps無し) + 不足.soをapt手動導入
cd /opt/dlogic/linebot && venv/bin/playwright install chromium   # --with-deps無しで試す
```
※ NARは静的HTMLで影響なし。JRAだけの問題。

### 確認2: netkeitaにJRAオッズが流れるか
6/6当日(土)、JRAプリフェッチが出来ていること + オッズ更新が反映されるか:
```bash
# 6/6のJRAプリフェッチ存在 (前日18:00のdlogic-jra-prefetch.timerが生成)
ls -la /opt/dlogic/linebot/data/prefetch/races_20260606.json
# JRAレースのオッズが非ゼロか
venv/bin/python -c "import json;d=json.load(open('/opt/dlogic/linebot/data/prefetch/races_20260606.json'));jra=[r for r in d['races'] if not r.get('is_local')];print('JRA',len(jra),'R');[print(r['venue'],r['race_number'],'odds',r['odds'][:4]) for r in jra[:3]]"
# サイト経由
curl -s "https://bot.dlogicai.in/nk/api/races" | head -c 300
```

---

## その他の保留(jin側のアクション待ち / 任意)
作業前にjinに状況確認。いずれも今のサービス稼働には必須ではない。

| 項目 | 内容 | 必要なもの |
|---|---|---|
| Anthropicクレジット | LINE/Telegram/netkeitaチャットのClaude応答が400エラー(残高ゼロ) | jinが console.anthropic.com で課金 |
| トルネード公開ドメイン | トルネードWebは:5001で稼働中だがnginx/DNS/TLS未設定 | jinに公開サブドメイン確認→DNS/nginx/certbot |
| オッズ監視(odds-monitor) | コード/venv/SUPABASE準備済・未起動 | jinから `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` |
| OPENAI_API_KEY | backendチャット系の警告解消(任意) | jinから値 |

## 完了済み(参考・再作業不要)
LINE Bot / 予想backend(全エンジン+レースレベル) / Telegram / netkeita(表示・NARリアルタイムオッズ・みんなの予想照合) / トルネードWeb / Redis / nginx+TLS / Supabase / 各タイマー(プリフェッチ・結果・オッズ更新・穴党・照合) はすべて稼働中。

---
_作成: 2026-06-03 / 対象: 2026-06-05(金)以降。完了したらこのファイルとメモリ `project_vps_outage_20260603` を更新。_
