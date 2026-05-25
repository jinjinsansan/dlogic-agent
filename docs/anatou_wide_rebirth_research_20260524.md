# 穴党参謀AI ワイド再構築 調査メモ 2026-05-24

## 目的

火水木の現行配信ルールをいったん前提から外し、バックエンド予測エンジンの上位5頭を使って、JRA・地方競馬を対象にワイド中心の優位性を再検証する。

今回の方針は「過去に見つけた単勝パターンの延命」ではなく、各エンジンの top5、合議、人気、券種別払戻を使って、穴党参謀AIをワイド型サービスとして作り直せるかを検証すること。

## 現時点の結論

- 検証に使える既存資産はかなり残っている。
- ただし、そのまま配信判断に使うには危険な点がある。
- JRAワイドは過去レポート上かなり強い候補がある。
- NARワイドは旧検証では全体的に弱く、地方競馬はゼロベースで再探索が必要。
- 最初にやるべきことは配信ロジック修正ではなく、データ監査と top5 ワイド用の正規データセット作成。

## 主要な場所

| 種別 | 場所 | 内容 |
|---|---|---|
| LINE Bot / 管理API | `E:\dev\Cusor\dlogic-agent` | Flask/API、Telegram配信、Supabase参照、既存バックテスト |
| 予測バックエンド | `E:\dev\Cusor\chatbot\uma\backend` | FastAPI、D/I/View/Meta/NLogic 予測 |
| 本番 LINE Bot | `/opt/dlogic/linebot` | VPS上の稼働想定 |
| 本番バックエンド | `/opt/dlogic/backend` | VPS上の予測API、port 8000 |
| 予測API | `POST /api/v2/predictions/newspaper` | 新聞形式入力から各エンジン top5 を返す |

## 現行の穴党参謀AI

仕様書:

- `docs/anatou_telegram_rebrand_spec.md`

配信スクリプト:

- `scripts/anatou_greet.py`
- `scripts/anatou_post_strict.py`
- `scripts/anatou_post_loose.py`
- `scripts/anatou_post_results.py`
- `scripts/anatou_correction_notice.py`
- `scripts/anatou_backfill_intro.py`
- `scripts/anatou_telegram_lib.py`

現行の主な配信条件:

- `api/data_api.py`
- Layer 1: NAR、火水木、旧5強場、6-12頭、5-8人気、4エンジン中2-3票一致、単勝
- Layer 2: 帯広中穴の複勝・ワイド候補。ただし現在 `LAYER2_ENABLED = False`
- Layer 3: JRAの複勝・馬連・三連複ロジック。ただし `anatou_post_strict.py` 側でJRA配信は停止されている

注意:

- `scripts/push_gantz_to_horse.py` など、内部名に GANTZ が残っている。
- `docs/droid_layer_audit_20260501.md` では表示回収率やLayer 3追加候補に関する修正提案が残っている。

## 予測エンジンの流れ

既存の呼び出し:

- `tools/executor.py` が `DLOGIC_API_URL/api/v2/predictions/newspaper` を呼び、各エンジンの top5 を取得する。
- `scripts/check_engine_results.py` も同じAPIを使い、日次で予測と結果を保存する。
- バックエンド側の `api/v2/predictions.py` は `dlogic`, `ilogic`, `viewlogic`, `metalogic`, `nlogic` を返す。

重要な注意:

- DB列名は `engine_hit_rates.top3_horses` だが、現在の `scripts/check_engine_results.py` は `top_horses[:5]` をこの列に保存している。
- つまり「列名は top3、実体は top5 の可能性」がある。
- 古いバックフィルや過去レポートでは top3 前提のものもあるため、長さ別・期間別・エンジン別に監査が必要。

## 払戻データ

使えるもの:

- `scrapers/race_result.py` は `win`, `fukusho`, `umaren`, `wide`, `umatan`, `sanrenpuku`, `sanrentan` を `race_results.result_json.payouts` に保存できる。
- `scripts/fetch_pckeiba_payouts_to_results.py` はローカルPCKEIBAから払戻をSupabaseへ補完する。
- `scripts/refetch_payouts.py` はnetkeibaから個別再取得する補助に使える。

検証前に確認すること:

- `race_results.result_json.payouts.wide` の期間別カバー率
- JRA/NAR別の払戻欠損
- race_id の内部形式と netkeiba/PCKEIBA 形式の突合
- 地方競馬の venue 補正

## 既存バックテスト資産

ワイド・多券種:

- `scripts/wide_recovery_analysis.py`
- `scripts/multi_ticket_consensus_backtest.py`
- `scripts/full_validation_clean.py`
- `scripts/nar_deep_pop_filter.py`
- `scripts/top5_analysis.py`

5エンジン/NLogic:

- `scripts/audit_5eng_step1_export.py`
- `scripts/audit_5eng_step2_predict.py`
- `scripts/audit_5engine_backtest.py`
- `docs/nlogic_5engine_deploy.md`
- `docs/audit_5engine_backtest_nar_20260501.md`

日次・保存系:

- `scripts/check_engine_results.py`
- `scripts/backfill_engine_hit_rates_from_pckeiba.py`
- `scripts/fetch_pckeiba_payouts_to_results.py`
- `scripts/update_bet_results.py`

参考ドキュメント:

- `docs/multi_ticket_analysis_plan.md`
- `docs/multi_ticket_clean_20260427.md`
- `docs/multi_ticket_consensus_backtest_20260427.md`
- `docs/full_validation_clean_20260427.md`
- `docs/nar_deep_pop_filter_20260427.md`
- `docs/engine_accuracy_audit_v2_20260426.md`
- `docs/engine_accuracy_audit_v5_FINAL_20260427.md`
- `docs/droid_layer_audit_20260501.md`
- `docs/gpt_prompt_mr_wide.md`
- `docs/weekday_mon_fri_backtest_20260503.md`

## 過去結果からのヒント

JRA:

- `docs/full_validation_clean_20260427.md` では、JRAの合議ワイドが強い。
- `W1_TOP2投票の_W1点`: n=372、回収率234.2%、CI下限188.0%
- `W2_TOP3投票の_W_BOX3`: n=1116、回収率248.2%、CI下限204.6%
- `docs/engine_accuracy_audit_v2_20260426.md` でも dlogic / metalogic / viewlogic の JRA ワイドに黒字候補がある。

NAR:

- `docs/nar_deep_pop_filter_20260427.md` では、NARワイドに強い全体傾向は見つかっていない。
- 帯広の一部に見込みはあったが、CIが弱く、その後Layer 2は停止されている。
- 旧Layer 1の火水木・単勝ルールは、今回のワイド再構築の出発点にはしない。

## 危険点

- 直近2週全外れにより、旧ルールはサービス上そのまま継続しにくい。
- `created_at <= race_date` のような日付だけの clean filter は、実運用の配信時刻前予測を保証しない。
- 現在モデルで過去レースを再予測したバックフィルは、当時のモデル性能ではなく現行モデルの過去適用になる。
- `top3_horses` 列の意味が期間で変わっている可能性がある。
- NLogic が本番VPSとローカルで同じ状態か未確認。
- PCKEIBA依存のスクリプトは、実行環境が揃わないと再現できない。
- NARは競馬場名、日付、race_id、払戻の突合ミスが起きやすい。

## 次に作るべきもの

### 1. データ監査スクリプト

候補:

- `scripts/wide_rebirth_data_audit.py`

確認項目:

- `engine_hit_rates` の期間、race_type、engine別件数
- `top3_horses` の配列長分布
- top5が本当に保存されている期間
- `race_results.result_json.payouts.wide` のカバー率
- `odds_snapshots` の人気データカバー率
- JRA/NAR別、開催場別、月別の欠損
- nlogic の有無

### 2. 正規データセット作成

候補:

- `data/wide_rebirth_dataset_YYYYMMDD_YYYYMMDD.jsonl`
- `scripts/build_wide_rebirth_dataset.py`

方針:

- できれば Supabase の既存 `engine_hit_rates` だけに依存せず、対象期間の出馬表をバックエンドAPIへ再投入して top5 を取り直す。
- 1 race 1 record に正規化する。
- engines は `dlogic`, `ilogic`, `viewlogic`, `metalogic`, `nlogic` を格納する。
- 払戻、人気、頭数、開催場、race_type、発走時刻、取得時刻を同梱する。

### 3. ワイド再構築バックテスト

候補:

- `scripts/wide_rebirth_backtest.py`

最低限試す戦略:

- W1: 合議投票 top2 のワイド1点
- W2: 合議投票 top3 のワイドBOX3点
- W3: 合議投票 top4 のワイドBOX6点
- W4: 合議投票 top5 のワイドBOX10点
- W5: 最多得票馬を軸に、AI穴馬へ流す
- W6: 人気馬1頭を軸に、AI穴馬へ流す
- W7: engine別 top5 BOX / top5から人気条件で抽出
- W8: NLogicあり・なし比較

必須の評価軸:

- 回収率
- 的中率
- 件数
- 月別回収率
- JRA/NAR別
- 競馬場別
- 人気帯別
- Bootstrap CI下限
- 最大払戻1件除外後の回収率
- 上位3払戻除外後の回収率
- 最長連敗
- 最大ドローダウン

### 4. サービス判断

検証が終わるまで、旧ルールを「推奨」表現で継続しない。

再開基準の例:

- 件数 n >= 300
- CI下限 >= 100%
- 月別で極端な1か月依存がない
- 上位1-3件の払戻を除いても黒字または実用水準
- 直近期間で壊れていない
- JRA/NARを分けた説明が可能

## 実装優先順位

1. `wide_rebirth_data_audit.py` を作る。
2. 既存DBの top5 / wide payout / odds coverage を数字で確認する。
3. 必要なら PCKEIBA + バックエンドAPIで正規データセットを再生成する。
4. `wide_rebirth_backtest.py` でワイド戦略を一括検証する。
5. レポートを `docs/wide_rebirth_backtest_*.md` に出す。
6. 勝てる条件だけを新しい穴党参謀AIの配信候補にする。

