# 穴党参謀AI 当日race-json生成 2026-05-25

## 目的

当日レースの出走表を、穴党参謀AIの診断パイプラインに渡せる `race-json` へ変換する。

既存の `scripts/prefetch_races.py` を使ってnetkeibaから出走表JSONを取得し、その出力を `scripts/anatou_prefetch_to_race_json.py` で変換する。

## 追加ファイル

- `scripts/anatou_prefetch_to_race_json.py`

## 入力

`scripts/prefetch_races.py` の出力:

- `data/prefetch/races_YYYYMMDD.json`

このJSONには以下が入る。

- race_id
- race_id_netkeiba
- venue
- race_number
- race_name
- horses
- horse_numbers
- posts
- jockeys
- odds
- popularities
- is_local

## 出力

`build_wide_rebirth_dataset_from_api.py` に渡せる形式:

- `data/anatou_races_both_YYYYMMDD.json`
- `data/anatou_races_jra_YYYYMMDD.json`
- `data/anatou_races_nar_YYYYMMDD.json`

形式は `audit_5eng_step1_export.py` の出力に寄せている。

主な項目:

- `payload`
- `pop_map`
- `meta`
- `result`

## 単体実行

```powershell
python scripts\anatou_prefetch_to_race_json.py `
  --input data\prefetch\races_YYYYMMDD.json `
  --race-type both `
  --out data\anatou_races_both_YYYYMMDD.json `
  --report docs\anatou_prefetch_to_race_json_both_YYYYMMDD.md
```

`--race-type` は `jra`, `nar`, `both` を指定できる。

## パイプライン一括実行

`scripts/anatou_today_pipeline.py` に `--prefetch-json` を追加した。

これにより、以下が一括実行できる。

```text
prefetch JSON
  -> race-json
  -> backend API replay
  -> wide JSONL
  -> race diagnosis JSONL
  -> preview Markdown/JSON
  -> forward log
```

実行例:

```powershell
python scripts\anatou_today_pipeline.py `
  --date YYYYMMDD `
  --prefetch-json data\prefetch\races_YYYYMMDD.json `
  --prefetch-race-type both `
  --api-url http://localhost:8011 `
  --preview-limit 8 `
  --forward-log
```

予測APIは別プロセスで起動しておく。

```powershell
uvicorn scripts.run_backend_predictions_only:app --host 127.0.0.1 --port 8011
```

## prefetchから始める場合

当日/翌日の出走表を取得する。

```powershell
python scripts\prefetch_races.py YYYYMMDD --all
```

NARだけ:

```powershell
python scripts\prefetch_races.py YYYYMMDD
```

JRAだけ:

```powershell
python scripts\prefetch_races.py YYYYMMDD --jra
```

## 検証結果

既存の `data/prefetch/races_20260311.json` で検証した。

単体変換:

- output: `data/anatou_races_both_20260311.json`
- records: 68
- with popularity: 68
- race_type: NAR 68
- venue: 船橋12、大井12、姫路12、名古屋12、金沢10、高知10

少数件パイプライン:

```powershell
python scripts\anatou_today_pipeline.py `
  --date 20260311 `
  --prefetch-json data\prefetch\races_20260311.json `
  --prefetch-race-type both `
  --api-url http://localhost:8011 `
  --limit 2 `
  --preview-limit 2 `
  --forward-log
```

結果:

- API replay input: 2
- output records: 2
- api errors: 0
- NLogicあり: 2/2
- engine_count: 5
- 診断: 2レース
- preview生成成功

## 現時点の実運用手順

1. 予測APIを起動する
2. `prefetch_races.py` で当日出走表を取得する
3. `anatou_today_pipeline.py --prefetch-json ... --forward-log` を実行する
4. `docs/anatou_forward/YYYYMMDD/preview.md` を確認する
5. Telegram送信はまだ行わず、まず数日分保存する
6. 結果確定後に `anatou_forward_result_check.py` を実行する

## 注意

- prefetch取得はnetkeibaへのアクセスが必要。
- 当日朝のオッズ/人気がないレースでは `pop_map` が薄くなる可能性がある。
- 予測APIが落ちている場合は `build_wide_rebirth_dataset_from_api.py` のAPI errorsが増える。
- まずはフォワードログ保存だけにし、配信文面や閾値は数日分を見てから調整する。
