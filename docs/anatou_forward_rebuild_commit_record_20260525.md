# 穴党参謀AI レース診断AI 再構築コミット記録 2026-05-25

## 目的

穴党参謀AIを、単純な買い目推奨から「競馬ファンの判断を助けるレース診断AI」へ作り替える。

既存のnetkeita向けバックエンドエンジン/API本体は変更しない。穴党参謀AI専用の検証・診断・フォワードログ層を追加した。

## 今回できたこと

### 1. 既存エンジン出力の再検証

- JRA/NARの既存データを監査
- API再生成データセットを作成
- 5エンジンtop5を使ったワイド/ペア検証を実施
- 結論として、買い目推奨としてすぐ有料化できる戦略は採用しない判断にした

主な記録:

- `docs/anatou_wide_rebirth_final_report_20260525.md`
- `docs/wide_rebirth_data_audit_20260525.md`
- `docs/wide_rebirth_dataset_build_20260525.md`
- `docs/wide_rebirth_backtest_20260525.md`

### 2. レース診断AIへ方針転換

新しい目的:

- 今日見るべきレース
- 荒れ警戒
- AI穴馬候補
- AI低評価人気
- AI一致レース
- 低優先度レース

計画書:

- `docs/anatou_pair_value_ai_development_plan_20260525.md`

### 3. 診断ロジック実装

追加:

- `scripts/anatou_race_diagnosis.py`
- `scripts/anatou_race_diagnosis_backtest.py`

生成・検証:

- JRA/NAR診断JSONL
- v1/v2バックテスト
- NAR会場別閾値

主な記録:

- `docs/anatou_race_diagnosis_backtest_summary_20260525.md`
- `docs/anatou_race_diagnosis_phase1_start_20260525.md`

### 4. 今日用プレビュー生成

追加:

- `scripts/anatou_today_diagnosis.py`

出力:

- `docs/anatou_today_diagnosis_preview_sample_20260525.md`
- `data/anatou_today_diagnosis_preview_sample_20260525.json`

### 5. 当日パイプライン化

追加:

- `scripts/anatou_today_pipeline.py`
- `scripts/anatou_prefetch_to_race_json.py`

対応フロー:

```text
prefetch JSON
  -> race-json
  -> backend API replay
  -> wide JSONL
  -> race diagnosis JSONL
  -> preview Markdown/JSON
  -> forward log
```

記録:

- `docs/anatou_today_payload_20260525.md`
- `docs/anatou_today_pipeline_20260525.md`

### 6. フォワードログと結果確認

追加:

- `scripts/anatou_forward_fetch_results.py`
- `scripts/anatou_forward_result_check.py`

できること:

- 日付別にpreview/manifest/diagnosisを保存
- netkeiba結果をローカルに取得
- 高配当ワイド、AI穴馬3着内相当、AI低評価人気の外れ率を確認

2026-05-25実データ:

- NAR prefetch: 60レース
- 診断対象: 50レース
- preview races: 28
- 結果取得済み: 38/50
- result_check突合: 18/28
- AI穴馬3着内相当: 4/39
- AI低評価人気3着内相当外: 8/23
- high wide races: 9/18

主な出力:

- `docs/anatou_forward/20260525/preview.md`
- `docs/anatou_forward/20260525/result_fetch.md`
- `docs/anatou_forward/20260525/result_check.md`
- `data/anatou_forward/20260525/preview.json`
- `data/anatou_forward/20260525/results_dataset.jsonl`

## 注意

- `api/data_api.py` は既存の未コミット変更であり、今回のコミット対象から外す。
- Telegram送信はまだ行わない。
- `AI低評価人気` は消し材料ではなく、表現は「人気馬の過信注意」に留める。
- `skip` はユーザー表示では「低優先度」とする。
- 買い目推奨ではなく、フォワード検証型のレース診断として運用する。

## 次の作業

1. 夜に2026-05-25の未取得12レースを再取得する。
2. `result_check.md` を再生成する。
3. 3-7日分のforward-logを貯める。
4. `daily_summary.md` を生成するスクリプトを追加する。
5. Telegram配信文面は、数日分の診断結果を見てから作る。
