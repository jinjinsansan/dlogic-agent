# 穴党参謀AI ワイド再構築 データ監査 2026-05-25

- 対象期間: 2026-03-01 〜 2026-05-25
- 処理: 読み取りのみ。Supabaseの更新なし。

## 総合判定

- engine_hit_rates unique races: 4,570
- top5入り候補レース: 1,692 (37.0%)
- 4エンジン揃い: 4,291 (93.9%)
- 5エンジン揃い: 0 (0.0%)
- NLogicあり: 0 (0.0%)
- race_idで結果と一致: 3,631 (79.5%)
- date/venue/race_numberで結果と一致: 3,601 (78.8%)
- 人気データあり: 2,916 (63.8%)
- wide払戻あり finished results: 3,012 (82.7%)

## engine_hit_rates

- rows: 17,832
- unique races: 4,570

### engine別

| engine | rows |
|---|---:|
| ilogic | 4,570 |
| metalogic | 4,570 |
| dlogic | 4,401 |
| viewlogic | 4,291 |

### race_type別

| race_type | rows |
|---|---:|
| nar | 14,428 |
| jra | 3,404 |

### top3_horses配列長

| length | rows |
|---|---:|
| 3 | 11,011 |
| 5 | 6,376 |
| 1 | 262 |
| 2 | 137 |
| 4 | 46 |

### 1レースあたりエンジン数

| engine_count | races |
|---|---:|
| 4 | 4,291 |
| 2 | 169 |
| 3 | 110 |

### created_atとrace dateの差

| bucket | rows |
|---|---:|
| same_day | 13,226 |
| later | 4,258 |
| next_day | 348 |

### 月別 engine rows

| month | rows |
|---|---:|
| 2026-04 | 6,571 |
| 2026-03 | 6,568 |
| 2026-05 | 4,693 |

## race_results

- rows: 3,642
- finished: 3,642
- payoutsあり: 3,012
- wide払戻あり: 3,012
- result_json parse失敗: 0

### 月別 finished results

| month | rows |
|---|---:|
| 2026-04 | 1,393 |
| 2026-05 | 1,212 |
| 2026-03 | 1,037 |

## odds_snapshots

- rows: 227,878
- unique races: 3,075
- odds_data有効payload: 227,878

### 月別 odds rows

| month | rows |
|---|---:|
| 2026-04 | 95,918 |
| 2026-05 | 87,827 |
| 2026-03 | 44,133 |

## 次の判断

- top5入り候補レースが少なければ、バックエンドAPIへ過去出馬表を再投入して top5 を再生成する。
- wide払戻カバー率が低ければ、`scripts/fetch_pckeiba_payouts_to_results.py` で補完する。
- 人気データの一致率が低ければ、PCKEIBA側の人気を使う正規データセット作成に切り替える。
- 5エンジン揃いが少なければ、まず4エンジン版と5エンジン版を分けて検証する。

