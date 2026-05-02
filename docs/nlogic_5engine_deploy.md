# NLogic 5基合議デプロイ手順

## 概要
NLogic (CatBoost ML エンジン) を 5基目として追加し、4基 vs 5基合議のエッジ差を検証する。

## 前提条件
- VPS (220.158.24.157) で dlogic-backend が稼働中
- CatBoost モデルファイルが `chatbot/uma/backend/data/` に存在
- PCKEIBA がローカルで稼働中

---

## Step 1: VPS backend に NLogic を追加

### 1.1 CatBoost モデルファイルを VPS に転送
```bash
scp E:\dev\Cusor\chatbot\uma\backend\data\nlogic_rank_model.cbm root@220.158.24.157:/opt/dlogic/backend/data/
scp E:\dev\Cusor\chatbot\uma\backend\data\nlogic_support_model.cbm root@220.158.24.157:/opt/dlogic/backend/data/
scp E:\dev\Cusor\chatbot\uma\backend\data\nlogic_nar_rank_model.cbm root@220.158.24.157:/opt/dlogic/backend/data/
scp E:\dev\Cusor\chatbot\uma\backend\data\nlogic_nar_support_model.cbm root@220.158.24.157:/opt/dlogic/backend/data/
```

### 1.2 NLogic エンジンファイルを VPS に転送
```bash
scp E:\dev\Cusor\chatbot\uma\backend\services\nlogic_engine.py root@220.158.24.157:/opt/dlogic/backend/services/
scp E:\dev\Cusor\chatbot\uma\backend\services\local_nlogic_engine.py root@220.158.24.157:/opt/dlogic/backend/services/
```

### 1.3 predictions.py を更新
```bash
scp E:\dev\Cusor\chatbot\uma\backend\api\v2\predictions.py root@220.158.24.157:/opt/dlogic/backend/api/v2/
```

### 1.4 CatBoost をインストール
```bash
ssh root@220.158.24.157 "cd /opt/dlogic/backend && source venv/bin/activate && pip install catboost"
```

### 1.5 numpy をインストール (NLogic 依存)
```bash
ssh root@220.158.24.157 "cd /opt/dlogic/backend && source venv/bin/activate && pip install numpy"
```

### 1.6 backend を再起動
```bash
ssh root@220.158.24.157 "systemctl restart dlogic-backend"
```

### 1.7 動作確認
```bash
ssh root@220.158.24.157 "curl -s -X POST http://localhost:8000/api/v2/predictions/newspaper \
  -H 'Content-Type: application/json' \
  -d '{\"race_id\":\"test\",\"horses\":[\"テスト馬A\",\"テスト馬B\",\"テスト馬C\"],\"horse_numbers\":[1,2,3]}' | python3 -m json.tool"
```
→ レスポンスに `"nlogic": [...]` が含まれていれば成功

---

## Step 2: バックテスト実行

### 2.1 NAR (Layer 1 検証)
```bash
python scripts/audit_5engine_backtest.py --race-type nar --since 20260301 --until 20260430
```

### 2.2 JRA (Layer 3 検証)
```bash
python scripts/audit_5engine_backtest.py --race-type jra --since 20260301 --until 20260430
```

### 2.3 結果確認
- `docs/audit_5engine_backtest_nar_YYYYMMDD.md`
- `docs/audit_5engine_backtest_jra_YYYYMMDD.md`

---

## Step 3: backfill (5基分のヒストリカルデータ蓄積)

backfill スクリプトは既に 5 エンジン対応済み:
```bash
python scripts/backfill_engine_hit_rates_from_pckeiba.py --race-type nar --since 20260301 --until 20260430
```
→ engine_hit_rates に `engine='nlogic'` の行が追加される

---

## Step 4: 結果判断

| 結果 | アクション |
|---|---|
| 5基合議の回収率 > 4基合議 + 10pt以上 | NLogic を正式採用、配信に組み込む |
| 差分 ±10pt 以内 | NLogic はフィルタとして補助的に使用 |
| 5基合議の回収率 < 4基合議 | NLogic は不採用、4基維持 |

---

## 注意事項
- NLogic の CatBoost モデルは 2025-10 学習。精度が落ちている可能性あり
- モデル再学習は `chatbot/uma/backend/scripts/` に学習スクリプトがある
- CatBoost は CPU のみで動作 (GPU 不要)、VPS のメモリ消費に注意
- NLogic はナレッジファイル依存 → `local_dlogic_raw_knowledge_v2.json` が VPS に必要
