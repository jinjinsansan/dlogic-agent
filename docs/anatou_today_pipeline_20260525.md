# 穴党参謀AI 当日診断パイプライン 2026-05-25

## 目的

穴党参謀AIの当日運用を、以下の順番で一括実行できるようにする。

1. レース単位のエンジン出力JSONLを用意する
2. レース診断JSONLを作る
3. ユーザー向け診断プレビューMarkdown/JSONを作る

既存のnetkeita向けバックエンドやAPI本体は変更しない。追加したのは穴党参謀AI用の薄い実行ラッパー。

## 追加ファイル

- `scripts/anatou_today_pipeline.py`

## 対応する入力

### 0. prefetch JSONから始める

`scripts/prefetch_races.py` の出力を直接渡せる。

```powershell
python scripts\anatou_today_pipeline.py `
  --date YYYYMMDD `
  --prefetch-json data\prefetch\races_YYYYMMDD.json `
  --prefetch-race-type both `
  --api-url http://localhost:8011 `
  --preview-limit 8 `
  --forward-log
```

内部では以下を実行する。

```text
prefetch JSON
  -> race-json
  -> backend API replay
  -> wide JSONL
  -> race diagnosis JSONL
  -> preview Markdown/JSON
```

### 1. 既存wide JSONLから始める

すでに `wide_rebirth_dataset` 形式のJSONLがある場合は、API再予測を行わずに診断とプレビューだけを作る。

```powershell
python scripts\anatou_today_pipeline.py `
  --date 20260314 `
  --wide-jsonl data\wide_rebirth_dataset_api_jra_20260301_20260430.jsonl `
  --wide-jsonl data\wide_rebirth_dataset_api_nar_20260301_20260430.jsonl `
  --preview-limit 6 `
  --out-md docs\anatou_today_pipeline_preview_20260314.md `
  --out-json data\anatou_today_pipeline_preview_20260314.json
```

### 2. race payload JSONから始める

`audit_5eng_step1_export.py` と同じ形式のレースpayload JSONがある場合は、バックエンド予測APIを呼んでwide JSONLを作ってから診断へ進む。

```powershell
python scripts\anatou_today_pipeline.py `
  --date YYYYMMDD `
  --race-json data\5eng_races_jra_YYYYMMDD_YYYYMMDD.json `
  --race-json data\5eng_races_nar_YYYYMMDD_YYYYMMDD.json `
  --api-url http://localhost:8011 `
  --preview-limit 8
```

予測APIは別プロセスで起動しておく。

```powershell
uvicorn scripts.run_backend_predictions_only:app --host 127.0.0.1 --port 8011
```

## 生成されるファイル

wide JSONLから始めた場合:

- `data/anatou_today_diagnosis_{source_stem}_{YYYYMMDD}.jsonl`
- `docs/anatou_today_diagnosis_build_{source_stem}_{YYYYMMDD}.md`
- `docs/anatou_today_pipeline_preview_{YYYYMMDD}.md`
- `data/anatou_today_pipeline_preview_{YYYYMMDD}.json`

race payload JSONから始めた場合は、追加で以下も生成される。

- `data/anatou_today_wide_{source_stem}_{YYYYMMDD}.jsonl`
- `docs/anatou_today_wide_{source_stem}_{YYYYMMDD}.md`

## ドライラン結果

既存のJRA/NAR再生成データを使い、2026-03-14を日付指定してドライランした。

出力:

- `docs/anatou_today_pipeline_preview_20260314.md`
- `data/anatou_today_pipeline_preview_20260314.json`

結果:

- total_races: 52
- low_priority: 22
- label:AI一致: 20
- label:低優先度: 22
- label:荒れ警戒: 7
- label:AI穴馬候補: 3

プレビュー例:

```text
穴党参謀AI 本日のレース診断プレビュー

今日見るべきレース
1. 2026-03-14 中山8R AI穴馬候補 / AI穴馬チェック
   - AI穴: 14番(11人気/AI4基)、5番(7人気/AI3基)

2. 2026-03-14 帯広11R 荒れ警戒 / 人気馬の過信注意
   - AI穴: 9番(9人気/AI3基)、1番(8人気/AI3基)
```

## 現時点の注意

- `skip` はユーザー表示では「低優先度」に変換する
- `danger_popular` は表示せず「AI低評価人気」「人気馬の過信注意」とする
- Telegram送信はまだ行わない
- まずはMarkdown/JSONを数日保存し、診断の読みやすさと妥当性を確認する

## 次の工程

フォワードログ保存用の固定ディレクトリと結果突合の準備を追加した。

追加ファイル:

- `scripts/anatou_forward_result_check.py`

## フォワードログ運用

当日診断を日付別に保存する場合は `--forward-log` を付ける。

```powershell
python scripts\anatou_today_pipeline.py `
  --date YYYYMMDD `
  --forward-log `
  --wide-jsonl data\today_jra_wide.jsonl `
  --wide-jsonl data\today_nar_wide.jsonl `
  --preview-limit 8
```

生成先:

- `docs/anatou_forward/YYYYMMDD/preview.md`
- `docs/anatou_forward/YYYYMMDD/manifest.md`
- `data/anatou_forward/YYYYMMDD/preview.json`
- `data/anatou_forward/YYYYMMDD/manifest.json`
- `data/anatou_forward/YYYYMMDD/diagnosis_1.jsonl`
- `data/anatou_forward/YYYYMMDD/diagnosis_2.jsonl`

## 結果確認

結果確定後、wide払戻を含むrace datasetが用意できたら以下を実行する。

```powershell
python scripts\anatou_forward_result_check.py `
  --preview-json data\anatou_forward\YYYYMMDD\preview.json `
  --race-dataset data\today_jra_wide_with_results.jsonl `
  --race-dataset data\today_nar_wide_with_results.jsonl `
  --out docs\anatou_forward\YYYYMMDD\result_check.md `
  --high-wide 1000
```

出力:

- `docs/anatou_forward/YYYYMMDD/result_check.md`

見る指標:

- AI穴馬が3着内相当に入ったか
- AI低評価人気が3着内相当を外したか
- 診断対象レースで高配当ワイドが出たか

これは買い目ROIではなく、診断ラベルがユーザーにとって意味のあるレースを拾えているかを見るための確認。

### forward-logからローカル結果datasetを作る

当日の `manifest.json` と `prefetch` がある場合は、Supabaseに書き込まずローカルだけで結果入りdatasetを作れる。

追加ファイル:

- `scripts/anatou_forward_fetch_results.py`

実行例:

```powershell
python scripts\anatou_forward_fetch_results.py `
  --manifest data\anatou_forward\YYYYMMDD\manifest.json `
  --prefetch data\prefetch\races_YYYYMMDD.json `
  --out data\anatou_forward\YYYYMMDD\results_dataset.jsonl `
  --report docs\anatou_forward\YYYYMMDD\result_fetch.md `
  --sleep 0.7
```

その後:

```powershell
python scripts\anatou_forward_result_check.py `
  --preview-json data\anatou_forward\YYYYMMDD\preview.json `
  --race-dataset data\anatou_forward\YYYYMMDD\results_dataset.jsonl `
  --out docs\anatou_forward\YYYYMMDD\result_check.md `
  --high-wide 1000
```

## フォワードログのドライラン

2026-03-14でドライラン済み。

生成:

- `docs/anatou_forward/20260314/preview.md`
- `docs/anatou_forward/20260314/manifest.md`
- `docs/anatou_forward/20260314/result_check.md`
- `data/anatou_forward/20260314/preview.json`
- `data/anatou_forward/20260314/manifest.json`

結果確認サマリ:

- preview races: 21
- outcome found: 21/21
- AI穴馬 3着内相当: 3/39
- AI低評価人気 3着内相当外: 8/16
- high wide races: 15/21

読み取り:

- 高配当が出やすいレースを拾う診断としては有望
- AI穴馬単体の3着内率はまだ低い
- AI低評価人気は半分程度で、断定的な消し材料にはしない

## prefetch接続のドライラン

`data/prefetch/races_20260311.json` からrace-json変換と少数件パイプラインを検証済み。

追加スクリプト:

- `scripts/anatou_prefetch_to_race_json.py`

単体変換結果:

- output: `data/anatou_races_both_20260311.json`
- records: 68
- with popularity: 68
- race_type: NAR 68

パイプライン少数件:

- input: `data/prefetch/races_20260311.json`
- limit: 2
- API replay records: 2
- api errors: 0
- NLogicあり: 2/2
- engine_count: 5
- preview生成成功

詳細は `docs/anatou_today_payload_20260525.md` を参照。
