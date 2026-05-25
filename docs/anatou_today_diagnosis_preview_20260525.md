# 穴党参謀AI 今日用診断プレビュー 2026-05-25

## 目的

診断JSONLを、Telegram配信前に確認できるMarkdown/JSONへ整形する。

この工程は既存バックエンドエンジンやnetkeita向けAPIを変更しない。入力済みの診断JSONLを読み取り、表示用のプレビューを作るだけ。

## 追加ファイル

- `scripts/anatou_today_diagnosis.py`

## 役割

以下の診断データを、ユーザー向けに読みやすい日次プレビューへ変換する。

- 今日見るべきレース
- AI穴馬候補
- AI低評価人気
- AI一致レース
- 低優先度レース

表現ルール:

- `danger_popular` とは表示しない
- 「危険人気馬」ではなく「AI低評価人気」「人気馬の過信注意」と表示する
- `skip` は「低優先度」と表示する
- 買い目推奨ではなく、フォワード検証用のレース診断として表示する

## 生成済みサンプル

- Markdown: `docs/anatou_today_diagnosis_preview_sample_20260525.md`
- JSON: `data/anatou_today_diagnosis_preview_sample_20260525.json`

入力:

- `data/anatou_race_diagnosis_v2_jra_20260301_20260430.jsonl`
- `data/anatou_race_diagnosis_v2_nar_20260301_20260430.jsonl`

実行コマンド:

```powershell
python scripts\anatou_today_diagnosis.py `
  --input data\anatou_race_diagnosis_v2_jra_20260301_20260430.jsonl `
  --input data\anatou_race_diagnosis_v2_nar_20260301_20260430.jsonl `
  --limit 8 `
  --out-md docs\anatou_today_diagnosis_preview_sample_20260525.md `
  --out-json data\anatou_today_diagnosis_preview_sample_20260525.json
```

## 今日データに使う場合

当日分の診断JSONLができている場合は、以下のように日付指定で実行する。

```powershell
python scripts\anatou_today_diagnosis.py `
  --input data\anatou_race_diagnosis_today_YYYYMMDD.jsonl `
  --date YYYYMMDD `
  --limit 8 `
  --out-md docs\anatou_today_diagnosis_preview_YYYYMMDD.md `
  --out-json data\anatou_today_diagnosis_preview_YYYYMMDD.json
```

## サンプル結果

全期間サンプルのため、実際の1日分より件数は多い。

- total_races: 1,738
- low_priority: 819
- label:低優先度: 819
- label:荒れ警戒: 348
- label:AI穴馬候補: 142
- label:AI一致: 429

プレビュー本文では、注目レース、AI穴馬候補、AI低評価人気、AI一致レースを上位件数だけ表示する。低優先度レースは会場ごとに件数と一部だけを表示する。

## 次の工程

次は、当日レースのエンジン出力から診断JSONLを作る工程を接続する。

候補:

1. 既存の `build_wide_rebirth_dataset_from_api.py` と `anatou_race_diagnosis.py` を当日用に直列実行する薄いラッパーを作る
2. `scripts/anatou_today_diagnosis.py` はその出力JSONLを読むだけにする
3. Telegram送信はまだ行わず、まずMarkdown/JSONのフォワードログを数日保存する
