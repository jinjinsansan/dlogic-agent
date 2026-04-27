# 競馬GANTZ GUI 自動投票 トラブルシュート記録 (2026-04-27)

**作成日**: 2026-04-27 (10時頃)
**対象**: HorseBet GUI (`E:/dev/Cusor/horse/horsebet-system/user-gui/`) の競馬GANTZ自動投票
**状態**: 13:23 の初回自動投票を待って動作検証中

---

## 0. 発生事象

今朝 09:08、GUI のイベントログで全7レースの「投票失敗」エラーが連発:

```
09:08 · エラー
水沢 11R 投票失敗 — 投票処理中にエラーが発生しました:
  browserType.launchPersistentContext: Executable doesn't exist at C:\Users\USER\A...
(他: 大井 2/6/9/10R, 水沢 8/10R)
```

→ Playwright が Chromium バイナリを見つけられず launch失敗。

---

## 1. 全体アーキテクチャ (再確認)

```
┌─────────────────────────────────────────┐
│ dlogic-agent (VPS 220.158.24.157)       │
│                                         │
│  scripts/push_gantz_to_horse.py         │
│   毎朝 09:01 cron 起動                   │
│   ↓ /api/data/golden-pattern/today を叩き │
│   ↓ Supabase bet_signals に upsert      │
└─────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────┐
│ Supabase (HORSE_SUPABASE)               │
│   bet_signals テーブル                   │
└─────────────────────────────────────────┘
              ↓ Realtime INSERT/UPDATE
┌─────────────────────────────────────────┐
│ HorseBet GUI (Electron + React)         │
│   E:/dev/Cusor/horse/horsebet-system/   │
│     user-gui/                           │
│                                         │
│   BetScheduler が bet_signals を購読     │
│   発走 5分前に Playwright で SPAT4自動投票 │
└─────────────────────────────────────────┘
```

### キーパス
- ブリッジスクリプト (VPS): `/opt/dlogic/linebot/scripts/push_gantz_to_horse.py`
- ブリッジ cron: `dlogic-push-gantz.timer` (毎朝 09:01)
- GUI ローカル: `E:/dev/Cusor/horse/horsebet-system/user-gui/`
- BetScheduler: `user-gui/src/services/bet-scheduler.ts`
- SPAT4 Voter: `horsebet-system/shared/automation/spat4-voter.ts`
- IPAT Voter: `horsebet-system/shared/automation/ipat-voter.ts`

---

## 2. 根本原因 (2つ複合)

### 原因A: Playwright Chromium バイナリ不在
- `user-gui/package.json` の Playwright バージョン: **1.56.1**
- 1.56.1 が要求する Chromium revision: **1194** (`browsers.json` で確認)
- jin の AppData (`C:\Users\USER\AppData\Local\ms-playwright/`) に存在: **chromium-1208, 1217** のみ → 1194 不在
- `user-gui/node_modules/.cache/ms-playwright/` には**実は1194 入っていた** (postinstall で前回入れた)
- しかし Electron 起動時に PLAYWRIGHT_BROWSERS_PATH を設定していなかった = AppData参照 → not found

#### 対応
```bash
# AppData にも 1194 を入れた (デフォルトpath)
npx playwright install chromium
# → C:\Users\USER\AppData\Local\ms-playwright\chromium-1194\ 展開
```

これでどちらの参照経路でも見つかるようになった。

### 原因B: bet_signals.start_time が None
- 朝09:01 にcron で投入された bet_signals 10件 全てが `start_time = NULL`
- 連鎖的に: BetScheduler の仕様 = 「**start_time 未指定 = 即時実行**」
- 09:08 時点で投票実行 → SPAT4 ページは「**発売前**」表示 → 投票拒否されてエラー

#### 原因の上流
- `dlogic-agent/scripts/push_gantz_to_horse.py` line 156: `"start_time": race.get("start_time") or None`
- API レスポンスの `start_time` が **空文字 ('')** → None として保存
- 元データ (prefetch JSON) で NAR の発走時刻が**取れていない**:
  - `data/prefetch/races_20260427.json` の 大井全レースで `start_time = ''`
- NAR scraper (`scrapers/nar.py`) は `.RaceList_ItemTime` を読むが、HTMLに該当要素なし (構造変化?)

---

## 3. 今日の応急対処 (実施済)

### Step 1: Playwright Chromium 1194 インストール
```bash
# AppData にもインストール
npx playwright install chromium
# → C:\Users\USER\AppData\Local\ms-playwright\chromium-1194\chrome-win64\chrome.exe
```

### Step 2: SPAT4 から発走時刻を手動取得
**大井 (jo_code=35)**:
- 2R 15:01 / 3R 15:34 / 5R 16:39 / 6R 17:11 / 9R 18:54 / 10R 19:29

**水沢 (jo_code=32)**:
- 4R 13:28 / 8R 15:48 / 10R 16:58 / 11R 17:33

### Step 3: bet_signals 10件 UPDATE
```python
import urllib.request, os, json
base = os.environ['HORSE_SUPABASE_URL'].rstrip('/')
hdrs = {'apikey': os.environ['HORSE_SUPABASE_SERVICE_ROLE_KEY'],
        'Authorization': f'Bearer {os.environ["HORSE_SUPABASE_SERVICE_ROLE_KEY"]}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'}

# 大井
oi_times = {2: '15:01', 3: '15:34', 5: '16:39', 6: '17:11', 9: '18:54', 10: '19:29'}
for race_no, st in oi_times.items():
    url = f"{base}/rest/v1/bet_signals?signal_date=eq.2026-04-27&jo_code=eq.35&race_no=eq.{race_no}"
    urllib.request.urlopen(urllib.request.Request(url, method='PATCH', headers=hdrs,
                                                    data=json.dumps({'start_time': st}).encode())).read()

# 水沢
mizu_times = {4: '13:28', 8: '15:48', 10: '16:58', 11: '17:33'}
for race_no, st in mizu_times.items():
    url = f"{base}/rest/v1/bet_signals?signal_date=eq.2026-04-27&jo_code=eq.32&race_no=eq.{race_no}"
    urllib.request.urlopen(urllib.request.Request(url, method='PATCH', headers=hdrs,
                                                    data=json.dumps({'start_time': st}).encode())).read()
```

### Step 4: GUI fresh restart
- 既存プロセス kill: vite (PID 40380, 昨日19:22から起動) + electron 4プロセス
- `npm run dev` で fresh起動 (`E:/dev/Cusor/horse/horsebet-system/user-gui/`)
- ダッシュボードで 10件全て「予約」ステータス確認 → ✅

---

## 4. 投票スケジュール (今日)

GUI が start_time を読んで **発走5分前に自動発射** する設計:

| Fire時刻 | 発走時刻 | レース | 買い目 |
|---|---|---|---|
| 13:23 | 13:28 | 水沢 4R | 単勝 7番 |
| 14:56 | 15:01 | 大井 2R | 単勝 13番 |
| 15:29 | 15:34 | 大井 3R | 単勝 8番 |
| 15:43 | 15:48 | 水沢 8R | 単勝 6番 |
| 16:34 | 16:39 | 大井 5R | 単勝 4番 |
| 16:53 | 16:58 | 水沢 10R | 単勝 3番 |
| 17:06 | 17:11 | 大井 6R | 単勝 12番 |
| 17:28 | 17:33 | 水沢 11R | 単勝 4番 |
| 18:49 | 18:54 | 大井 9R | 単勝 12番 |
| 19:24 | 19:29 | 大井 10R | 単勝 6番 |

→ **13:23 が最初の自動投票発射** (動作検証ポイント)

---

## 5. 明日以降の課題 (未対応 TODO)

### 必須対応
1. **`scripts/push_gantz_to_horse.py` で start_time を空にしない**
   - prefetch JSON が空のままでも、別ソースから発走時刻取得して埋める
   - 候補ソース: SPAT4 / netkeiba (`.RaceList_ItemTime` HTML構造変化を確認・修正) / nvd_ra (PCKEIBA)

2. **prefetch JSON 生成側で start_time を取得する**
   - `scripts/daily_prefetch.py` 等 (NAR分の発走時刻取得が漏れている)
   - 取得元のスクレイピングロジック修正が必要

3. **GUI に「発売前エラーをリトライする」ロジック追加**
   - 現在は失敗時 in-memory で `failed` → 再試行なし
   - 「発売前」エラーは時刻待ちで再試行可能 → 5分後リトライ等

### 確認済み事項
- jo_code マッピング: **35 = 大井, 32 = 水沢** (push_gantz_to_horse.py の `NAR_JO_CODES` で定義)
- bet_history は0件 (= 失敗時 history に書き込まれない設計)
- BetScheduler の重複防止は signal_id ベース、status='active' のままなら GUI再起動で再読み込みされる
- Playwright Chromium は両方 (`AppData/Local/ms-playwright/` と `node_modules/.cache/ms-playwright/`) にインストール済

---

## 6. 検証ポイント

13:23 で水沢4R の自動投票発射が走った時:

### 成功シナリオ
- イベントログ: 「水沢 4R 投票完了」「投票完了 1件」
- ダッシュボード: 該当レース → ステータス「submitted」
- bet_history テーブル: signal_id=16 のレコード追加

### 失敗シナリオの想定
- Playwright エラー: 再度 Chromium パス問題 → PLAYWRIGHT_BROWSERS_PATH の指定を main.ts で実装する必要
- SPAT4 ログイン失敗: credentials 設定漏れ
- レース存在せず: スクレイピングセレクタ古い等

---

## 7. ファイル一覧 (今日作業対象)

### 編集済 (読み取りのみ、修正なし)
- `dlogic-agent/scripts/push_gantz_to_horse.py` (今後修正予定)
- `horse/horsebet-system/shared/automation/spat4-voter.ts`
- `horse/horsebet-system/user-gui/src/services/bet-scheduler.ts`
- `horse/horsebet-system/user-gui/package.json`

### 直接データ操作
- Supabase `bet_signals` テーブル (10件 UPDATE)

### 新規作成
- (なし)

---

## 8. 関連ドキュメント

- `docs/keiba_gantz_runbook_v5.md` (v5 運用仕様)
- `docs/engine_accuracy_audit_v5_FINAL_20260427.md` (v5 監査)
- `horsebet-system/GANTZ_INTEGRATION_PLAN.md` (連携設計)
- `horsebet-system/SPAT4_ORIGINAL_FLOW.md` (SPAT4 投票フロー)

---

**ステータス**: 13:23 の自動投票結果待ち
**次のアクション**: 13:23 で水沢4R 投票成功確認 → 明日以降のための push_gantz 修正へ
