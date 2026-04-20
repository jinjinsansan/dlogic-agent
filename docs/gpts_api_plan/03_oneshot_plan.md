# GPTs公開用 軽量ナレッジJSON 生成計画

作成日: 2026-04-21
対象: 一回限りスクリプト `generate_gpts_knowledge.py`(新規作成予定)
成果物: `public/gpts_jockey_stats.json`, `public/gpts_course_insights.json`, `public/gpts_bloodline_insights.json` を R2 `dlogic-knowledge-files` にアップロード

---

## 1. 騎手データ: 構造とソース

### 1.1 ローカルに存在する候補ファイル

| ファイル | サイズ | 更新日 | エントリ数 | 備考 |
|---|---|---|---|---|
| `E:\dev\Cusor\chatbot\uma\backend\data\extended_jockey_knowledge.json` | 9.6MB | 2025-08-21 | **562騎手** | 旧版。各騎手 `total_races_analyzed=9` とサンプル少 |
| `E:\dev\Cusor\chatbot\uma\backend\data\jockey_knowledge.json` | **93MB** | 2025-09-23 | **846騎手** | 新版。フィールドは `venue_course_stats` に距離単位付(例 `中山_2500m`) |
| `E:\dev\Cusor\chatbot\uma\backend\data\jockey_knowledge_9races.json` | 41MB | 2025-09-23 | 不明 | 9走限定版 |
| **R2 `jra_jockey_knowledge_latest.json`** | 不明 | 週次月曜 | 不明 | **本番が参照する最新版**。`_latest` エイリアス運用 |

> 一回限りスクリプトの推奨ソース: **R2の `jra_jockey_knowledge_latest.json` をHTTP GETして使う**(ローカルより鮮度が高く、`jockey_knowledge.json` の93MBを読み込む必要もない)。フォールバックとして `jockey_knowledge.json` を使えるようにしておく。

### 1.2 トップレベル構造

実ファイル(`extended_jockey_knowledge.json`)を Python で確認した結果:

- トップレベル: **騎手名(日本語)をキーとする辞書** (コード番号ではない)
- 騎手名には全角スペースのパディングが入ることがある(`"幸英明　"` のように)
- 新版(`jockey_knowledge.json`)も同じ構造

### 1.3 各騎手エントリのフィールド

確定済みフィールド(extended_jockey_knowledge.json の実データ確認):

| フィールド | 型 | 内容 |
|---|---|---|
| `venue_course_stats` | dict | `"中山_2000": {races, wins, top3, win_rate, top3_rate}` |
| `track_condition_stats` | dict | `"良"/"稍重"/"重"/"不良"` ごとの成績 |
| `post_position_stats` | dict | 枠番(1-8)ごとの成績 |
| `sire_stats` | dict | 父馬別成績(実データではしばしば空) |
| `overall_stats` | dict | `{total_races_analyzed, overall_win_rate, overall_top3_rate}` |
| `venue_course_full_stats` | dict | `"中山_1800": {total_races, wins, win_rate, top3_rate}` — より広範な集計 |
| `bloodline_stats` | dict | 血統系統別成績 |
| `post_position_by_course` | dict | コース別枠順成績 |
| `last_updated` | string | 更新日時 |

### 1.4 軽量化戦略

#### 軽量版スキーマ(提案)
```json
{
  "meta": {
    "generated_at": "2026-04-21T...",
    "source": "jra_jockey_knowledge_latest.json",
    "jockeys_count": 50
  },
  "jockeys": {
    "騎手名": {
      "overall": {"win_rate": 0.15, "top3_rate": 0.42},
      "top_venues": [
        {"venue": "中山", "distance": 2000, "win_rate": 0.20, "top3_rate": 0.50, "races": 31}
      ],
      "track_condition": {"良": 0.42, "稍重": 0.38, "重": 0.30, "不良": 0.25}
    }
  }
}
```

#### 絞り込み方針

| 軸 | 軽量化手法 |
|---|---|
| 騎手の数 | `overall_stats.total_races_analyzed`(または `venue_course_full_stats` の合計) **降順で上位30〜50人** に絞る |
| 会場×距離 | 各騎手につき `venue_course_full_stats` を **races 降順で上位5コース** のみ残す |
| フィールド | `post_position_stats`, `bloodline_stats`, `sire_stats`, `post_position_by_course` は **除外**(GPTs向けには冗長) |
| 小数精度 | win_rate/top3_rate は **小数第3位まで** で丸め |

#### 推奨する絞り込み人数

「記事配布用途で有名騎手がカバーされていれば十分」という前提:

| 絞り込み | 結果 |
|---|---|
| **30人** | JRA重賞常連(ルメール、川田、武豊、戸崎、モレイラ、横山武 他)を確実にカバー。ファイル約100KB |
| **50人** | 準重賞クラスまでカバー。ファイル約200KB |
| 100人 | ローカル騎手も一部含む。約400KB |
| 全846人 | 軽量化の意味がほぼ消える(93MB → 10MB程度) |

**推奨: 50人**(GPTsの回答速度・ファイル読み込みコストを考慮し、中間解)

### 1.5 全騎手数とランキング

| 指標 | 値 |
|---|---|
| 全騎手数(extended版) | 562 |
| 全騎手数(jockey_knowledge.json) | 846 |
| 実R2版(`_latest`)の件数 | **不明**(取得が必要) |

---

## 2. コース傾向: データソースと集計方針

### 2.1 既存JSONで直接使えるものは**存在しない**

grep 結果を整理:

| 探した対象 | 結果 |
|---|---|
| `course_stats.json` / `track_stats.json` 等の単独ファイル | **存在せず** |
| services層にコース特性辞書(静的な定数) | **存在せず**(venue_map はあるが会場コード↔名前の対応表のみ) |
| `venue_course_stats` を含むJSON | あり — **騎手ナレッジ内の騎手別コース成績**(騎手視点であり、コース自体の傾向ではない) |

### 2.2 集計が必要 — 元データは `dlogic_raw_knowledge.json`

実データ確認結果:

| 項目 | 値 |
|---|---|
| パス | `E:\dev\Cusor\chatbot\uma\backend\data\dlogic_raw_knowledge.json` |
| サイズ | 292MB |
| トップレベル | `{"metadata": {...}, "horses": {...}}` |
| 馬数 | **39,674頭** |
| 馬あたりのレース数 | 最大5(平均5) |
| 推定総レコード | 約20万 |
| 後継(R2) | `jra_knowledge_latest.json` |

### 2.3 使えるフィールド(1レース = 38項目)

各レース(`horses[馬名].races[i]`)に含まれる集計軸・指標:

| フィールド | 用途 |
|---|---|
| `KEIBAJO_CODE` | 会場(例 `"06"` = 中山) |
| `KYORI` | 距離(例 `"1800"`) |
| `TRACK_CODE` | 芝/ダート区別 |
| `SHIBA_BABAJOTAI_CODE` / `DIRT_BABAJOTAI_CODE` | 馬場状態 |
| `TENKO_CODE` | 天候 |
| `KAKUTEI_CHAKUJUN` | 確定着順(集計のキー) |
| `TANSHO_NINKIJUN` | 単勝人気順位 |
| `CORNER1_JUNI`〜`CORNER4_JUNI` | 脚質判定用 |
| `KOHAN_3F` / `ZENHAN_3F` | 上がり/前半3F |

### 2.4 会場コード → 会場名マッピング

複数箇所にハードコード済み(例: `api/race_data.py:63`):
```
'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
'06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'
```
一回限りスクリプトで再定義すれば十分(importしなくてよい)。

### 2.5 集計ロジック骨子(疑似コード・実装しない)

```
from collections import defaultdict

counters = defaultdict(lambda: {"races": 0, "wins": 0, "top3": 0, "favorite_wins": 0})

for horse_name, horse_data in knowledge["horses"].items():
    for race in horse_data.get("races", []):
        venue = VENUE_MAP.get(race.get("KEIBAJO_CODE"), "不明")
        distance = int(race.get("KYORI", 0))
        track_code = race.get("TRACK_CODE", "")
        surface = classify_surface(track_code)  # 芝 / ダート
        # キー例: ("中山", 2000, "芝")
        key = (venue, distance, surface)
        chaku = int(race.get("KAKUTEI_CHAKUJUN") or "99")
        ninki = int(race.get("TANSHO_NINKIJUN") or "99")

        counters[key]["races"] += 1
        if chaku == 1:
            counters[key]["wins"] += 1
            if ninki == 1:
                counters[key]["favorite_wins"] += 1
        if 1 <= chaku <= 3:
            counters[key]["top3"] += 1

# 統計値を計算
insights = []
for (venue, distance, surface), c in counters.items():
    if c["races"] < 100:  # サンプル少のコースは除外
        continue
    insights.append({
        "venue": venue,
        "distance": distance,
        "surface": surface,
        "total_races": c["races"],
        "favorite_win_rate": c["favorite_wins"] / c["wins"] if c["wins"] else 0,
        "upset_rate": 1 - (c["favorite_wins"] / c["wins"]) if c["wins"] else 0,
        # 追加可能: ペース傾向、上がり3F傾向、等
    })
```

### 2.6 軽量版スキーマ(提案)

```json
{
  "meta": {"generated_at": "...", "source": "dlogic_raw_knowledge.json"},
  "courses": [
    {
      "venue": "中山", "distance": 2000, "surface": "芝",
      "total_races": 820,
      "favorite_win_rate": 0.32,
      "upset_tendency": "中",
      "avg_winning_3f": 34.5
    }
  ]
}
```

JRA10会場 × 主要距離10種 × 芝/ダート2種 = 最大200レコード = 約30KB。

### 2.7 集計コスト注意

- 292MBを読む時点で2〜3GB RAM消費(Python dict展開)
- 解決策: `ijson` でストリーミング or 32bitは諦めて64bit Python で実行
- 解決策2: 今回はR2の`jra_knowledge_latest.json`を直接ダウンロードしてストリーミング解析する

---

## 3. 血統データ: データソースと集計方針

### 3.1 専用の血統JSONは**存在しない**

| 探した対象 | 結果 |
|---|---|
| `bloodline_knowledge.json` / `sire_knowledge.json` 等 | **存在せず** |
| 血統分析エンジンのデータ源 | `services/sire_performance_analyzer.py` が **オンザフライで生データから集計** |

### 3.2 馬別過去走データに血統フィールドあり

`dlogic_raw_knowledge.json` の `horses[X].races[Y]` に以下のフィールドが含まれる(実データ確認):

| フィールド | 内容 | サンプル |
|---|---|---|
| `sire` | **父馬名**(文字列) | (例: "シニスターミニスター") |
| `broodmare_sire` | **母父馬名**(文字列) | (例: "Old Trieste") |
| `dam` | 母馬名 | しばしば空文字列 |
| `KETTO_TOROKU_BANGO` | 血統登録番号 | "2018102133" |

※サンプル値は日本語エンコーディングの都合で完全表示できないが、フィールドは確認済み。

### 3.3 既存エンジンの集計ロジック

`services/sire_performance_analyzer.py` のパターンを参考にできる(コード変更せずパターンを流用):

1. 起動時に `horses` 辞書全走査 → `sire_index[sire名] = [{name, races}, ...]` を構築
2. `analyze_sire_performance(sire_name, venue_code, distance, track_type)` で:
   - `sire_index[sire名]` から全産駒を取得
   - 各産駒の全レースを KEIBAJO_CODE × KYORI × TRACK_CODE でフィルタ
   - 着順1/1-3をカウント → 勝率/複勝率

### 3.4 軽量版スキーマ(提案)

```json
{
  "meta": {"generated_at": "...", "source": "dlogic_raw_knowledge.json"},
  "sires": [
    {
      "sire": "ディープインパクト",
      "total_offspring": 850,
      "top_courses": [
        {"venue": "京都", "distance": 1800, "surface": "芝",
         "win_rate": 0.18, "top3_rate": 0.48, "sample": 240},
        {"venue": "東京", "distance": 2400, "surface": "芝",
         "win_rate": 0.16, "top3_rate": 0.46, "sample": 180}
      ]
    }
  ],
  "broodmare_sires": [ /* 母父版 */ ]
}
```

### 3.5 絞り込み方針

- 父馬: **産駒数100頭以上** または **総レース数500以上** の種牡馬のみ(上位50〜100頭程度)
- 母父: 同様の閾値
- 各種牡馬: `top_courses` は勝率×サンプル数でソートして上位5コース
- 推定ファイルサイズ: 父100頭+母父100頭 × 5コース = 約100KB

---

## 4. R2アップロードの最短手順

### 4.1 既存スクリプトの流用可否

| スクリプト | 流用性 | 備考 |
|---|---|---|
| `scripts/simple_r2_upload.py` | **△ 関数だけ流用可** | `sign_aws4_auth()`, `upload_file(file_path, object_name)` は汎用 / main() はハードコード済み |
| `scripts/weekly_knowledge_update.py` の `upload_to_r2()` | **○ そのまま使える** | `boto3.client('s3', ...)` で `s3.upload_file(filepath, R2_BUCKET, r2_key)` |
| `scripts/upload_r2.sh` | ✕ curlベース、対象ファイル名ハードコード |  |

### 4.2 推奨する書き方(疑似コード)

**方式A: boto3(`weekly_knowledge_update.py` パターン)**
```python
import boto3
from botocore.config import Config

# 環境変数から読む(ハードコード避ける)
s3 = boto3.client('s3',
    endpoint_url=os.environ['R2_ENDPOINT'],
    aws_access_key_id=os.environ['R2_ACCESS_KEY'],
    aws_secret_access_key=os.environ['R2_SECRET_KEY'],
    config=Config(signature_version='s3v4'),
    region_name='auto',
)

s3.upload_file(
    'local/gpts_jockey_stats.json',
    'dlogic-knowledge-files',
    'public/gpts_jockey_stats.json',  # ← "public/" プレフィックス
    ExtraArgs={
        'ContentType': 'application/json',
        'CacheControl': 'public, max-age=3600',  # GPTs向けにキャッシュ指定
    },
)
```

**方式B: simple_r2_upload.py の関数を import して再利用**
```python
from scripts.simple_r2_upload import upload_file
upload_file('local/gpts_jockey_stats.json', 'public/gpts_jockey_stats.json')
```
ただし `simple_r2_upload.py` の `BUCKET` 定数がハードコードなので、そのまま。

### 4.3 プレフィックス `public/` の扱い

R2(S3互換)はオブジェクトキーに `/` を含めるだけで仮想フォルダ扱いになる。バケットレベルでの設定変更は**不要**。

### 4.4 アップロード後のURL形式

| R2キー | パブリックURL |
|---|---|
| `public/gpts_jockey_stats.json` | `https://pub-059afaafefa84116b57d57e0a72b81bd.r2.dev/public/gpts_jockey_stats.json` |
| `public/gpts_course_insights.json` | `https://pub-059afaafefa84116b57d57e0a72b81bd.r2.dev/public/gpts_course_insights.json` |
| `public/gpts_bloodline_insights.json` | `https://pub-059afaafefa84116b57d57e0a72b81bd.r2.dev/public/gpts_bloodline_insights.json` |

※ 現状のバケットは Public Access(r2.dev)有効。カスタムドメインは未設定。

### 4.5 動作確認手順

1. curl で HEAD リクエスト → `200 OK` を確認
   `curl -I https://pub-059afaafefa84116b57d57e0a72b81bd.r2.dev/public/gpts_jockey_stats.json`
2. ブラウザでURLを開いて生JSONが見えるか
3. Content-Type が `application/json` になっているか

---

## 5. 新規スクリプトの配置場所提案

### 5.1 候補3つ

| 候補 | パス | ○ | × |
|---|---|---|---|
| **候補A(推奨)** | `E:\dev\Cusor\chatbot\uma\backend\scripts\generate_gpts_knowledge.py` | 既存のscripts/と同居でデータ相対パスが短い | scripts/ が一回限り/継続両方混在している点は既存の慣習 |
| 候補B | `E:\dev\Cusor\chatbot\uma\backend\oneoff\generate_gpts_knowledge.py` | 一回限りが明示的 | 新規ディレクトリ作成が必要、gitignore的に曖昧 |
| 候補C | `E:\dev\Cusor\dlogic-agent\scripts\generate_gpts_knowledge.py` | dlogic-agent内にまとまる | データ(`chatbot/uma/backend/data/`)へのパスが相対的に長く、import不可 |

### 5.2 推奨: **候補A**

理由:
- データファイル(`../data/dlogic_raw_knowledge.json`)に相対パスでアクセスしやすい
- 既存の `simple_r2_upload.py` を `from scripts.simple_r2_upload import ...` でimportしやすい
- 命名パターン(`create_*.py`, `update_*.py`, `simple_upload_*.py`)と自然に並ぶ

### 5.3 依存する既存モジュールの import 経路

候補A(`scripts/generate_gpts_knowledge.py`)からの想定 import:

```python
# 必要最小限
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

# 任意(R2アップロードに使う場合)
import boto3  # 方式A
# または
from scripts.simple_r2_upload import sign_aws4_auth  # 方式B

# 参考(血統集計ロジックのパターンを読むだけ — 依存しない)
# services/sire_performance_analyzer.py
```

プロジェクト既存モジュールへの import は**不要**(独立スクリプト)。`services/` から何も import せず、生JSONを直接読み集計する設計が一回限り用途に最適。

---

## 6. 想定される実装の全体像(疑似コードレベル)

`generate_gpts_knowledge.py` が行う処理を段階ごとに記述(実装はしない)。

### 6.1 全体フロー

```
[Step 1] 入力データ取得
         ├ jockey: R2 https://pub-.../jra_jockey_knowledge_latest.json を GET(またはローカル fallback)
         └ horses: ローカル data/dlogic_raw_knowledge.json を open(またはR2の jra_knowledge_latest.json)

[Step 2] 軽量化1: gpts_jockey_stats.json を生成
         ├ 騎手を total_races_analyzed 降順にソート
         ├ 上位50人に絞る
         ├ 各騎手: overall + venue_course_full_stats の上位5コース + track_condition_stats
         └ json.dump(ensure_ascii=False)

[Step 3] 軽量化2: gpts_course_insights.json を生成
         ├ horses 辞書を全走査
         ├ (venue, distance, surface) でカウンタ集計
         ├ total_races >= 100 のコースのみ採用
         └ json.dump

[Step 4] 軽量化3: gpts_bloodline_insights.json を生成
         ├ horses 辞書を全走査し sire_index / broodmare_sire_index を構築
         ├ 産駒100頭以上の sire / broodmare_sire のみ採用
         ├ 各々について (venue, distance, surface) 別勝率を計算、top5 抽出
         └ json.dump

[Step 5] R2 へアップロード
         ├ public/gpts_jockey_stats.json
         ├ public/gpts_course_insights.json
         └ public/gpts_bloodline_insights.json

[Step 6] 動作確認
         └ 各URLへ HEAD リクエスト、200 OKをログ出力
```

### 6.2 段階別の疑似コード

```python
def main():
    # Step 1
    jockey_data = load_jockey_data()    # R2 or local fallback
    horse_data  = load_horse_data()      # local dlogic_raw_knowledge.json

    # Step 2
    jockey_lite = build_jockey_lite(jockey_data, top_n=50)
    save_json(jockey_lite, 'out/gpts_jockey_stats.json')

    # Step 3
    course_lite = build_course_insights(horse_data, min_races=100)
    save_json(course_lite, 'out/gpts_course_insights.json')

    # Step 4
    bloodline_lite = build_bloodline_insights(horse_data, min_offspring=100, top_courses=5)
    save_json(bloodline_lite, 'out/gpts_bloodline_insights.json')

    # Step 5
    for local_name in ['gpts_jockey_stats', 'gpts_course_insights', 'gpts_bloodline_insights']:
        upload_to_r2(f'out/{local_name}.json', f'public/{local_name}.json')

    # Step 6
    verify_public_urls([
        'public/gpts_jockey_stats.json',
        'public/gpts_course_insights.json',
        'public/gpts_bloodline_insights.json',
    ])
```

### 6.3 関数ごとの骨子

#### `load_jockey_data()`
```
try:
    resp = requests.get('https://pub-...r2.dev/jra_jockey_knowledge_latest.json', timeout=60)
    return resp.json()
except Exception:
    return json.load(open('../data/jockey_knowledge.json'))
```

#### `build_jockey_lite(data, top_n)`
```
ranked = sorted(data.items(),
                key=lambda kv: kv[1].get('overall_stats', {}).get('total_races_analyzed', 0),
                reverse=True)
out = {}
for name, stats in ranked[:top_n]:
    vcfs = stats.get('venue_course_full_stats', {})
    top_courses = sorted(vcfs.items(), key=lambda kv: kv[1]['total_races'], reverse=True)[:5]
    out[name.strip()] = {
        'overall': stats.get('overall_stats'),
        'top_venues': [{'venue_distance': k, **v} for k, v in top_courses],
        'track_condition': stats.get('track_condition_stats'),
    }
return {'meta': {...}, 'jockeys': out}
```

#### `build_course_insights(data, min_races)`
```
VENUE_MAP = {'01': '札幌', '02': '函館', ..., '10': '小倉'}
counters = defaultdict(lambda: {'races':0,'wins':0,'top3':0,'fav_wins':0})
for _, horse_data in data['horses'].items():
    for race in horse_data.get('races', []):
        key = (VENUE_MAP.get(race['KEIBAJO_CODE']), int(race['KYORI']), classify_surface(race['TRACK_CODE']))
        counters[key]['races'] += 1
        if int(race.get('KAKUTEI_CHAKUJUN') or 99) == 1: counters[key]['wins'] += 1
        if int(race.get('KAKUTEI_CHAKUJUN') or 99) <= 3: counters[key]['top3'] += 1
        if int(race.get('TANSHO_NINKIJUN') or 99) == 1 and int(race.get('KAKUTEI_CHAKUJUN') or 99) == 1:
            counters[key]['fav_wins'] += 1
return {'meta': {...}, 'courses': [... for k,v in counters.items() if v['races'] >= min_races]}
```

#### `build_bloodline_insights(data, min_offspring, top_courses)`
```
sire_idx = defaultdict(list)
broodmare_idx = defaultdict(list)
for horse_name, hd in data['horses'].items():
    races = hd.get('races', [])
    sire = next((r.get('sire') for r in races if r.get('sire')), None)
    broodmare = next((r.get('broodmare_sire') for r in races if r.get('broodmare_sire')), None)
    if sire: sire_idx[sire].append(races)
    if broodmare: broodmare_idx[broodmare].append(races)

def aggregate(idx):
    result = []
    for sire_name, offspring_races_lists in idx.items():
        if len(offspring_races_lists) < min_offspring: continue
        course_stats = defaultdict(lambda: {'races':0,'wins':0,'top3':0})
        for races in offspring_races_lists:
            for race in races:
                key = (VENUE_MAP.get(race['KEIBAJO_CODE']), int(race['KYORI']), classify_surface(race['TRACK_CODE']))
                course_stats[key]['races'] += 1
                if int(race.get('KAKUTEI_CHAKUJUN') or 99) == 1: course_stats[key]['wins'] += 1
                if int(race.get('KAKUTEI_CHAKUJUN') or 99) <= 3: course_stats[key]['top3'] += 1
        # top-5 courses by races
        top = sorted(course_stats.items(), key=lambda kv: kv[1]['races'], reverse=True)[:top_courses]
        result.append({'sire': sire_name, 'total_offspring': len(offspring_races_lists), 'top_courses': [...]})
    return result

return {'meta': {...}, 'sires': aggregate(sire_idx), 'broodmare_sires': aggregate(broodmare_idx)}
```

#### `upload_to_r2(local_path, r2_key)`
```
import boto3
s3 = boto3.client('s3',
    endpoint_url=os.environ['R2_ENDPOINT'],
    aws_access_key_id=os.environ['R2_ACCESS_KEY'],
    aws_secret_access_key=os.environ['R2_SECRET_KEY'],
    config=Config(signature_version='s3v4'),
    region_name='auto')
s3.upload_file(local_path, 'dlogic-knowledge-files', r2_key,
               ExtraArgs={'ContentType': 'application/json',
                          'CacheControl': 'public, max-age=3600'})
```

---

## 付記: 実装前の確認事項(仁さん向け意思決定ポイント)

1. **絞り込み閾値の最終決定**
   - 騎手: 50人で合意? 30人に減らす?
   - コース: `min_races=100` で合意? 50に下げて全コース掲載?
   - 血統: 父馬を100頭以上に限定? 50以上? 着順の閾値は?

2. **データソースの選択**
   - 騎手データ: 新鮮な **R2版(`jra_jockey_knowledge_latest.json`)** vs 手元の `jockey_knowledge.json`(93MB・2025年9月)
   - 馬データ: ローカル `dlogic_raw_knowledge.json`(292MB・2025年9月)を使う or R2の `jra_knowledge_latest.json` をDL

3. **R2認証情報の渡し方**
   - 現状鍵はソースにハードコード済み(前回レポート指摘)
   - 一回限りなら環境変数 `R2_ACCESS_KEY` / `R2_SECRET_KEY` / `R2_ENDPOINT` を事前セット、スクリプトは `os.environ[...]` で読む
   - これなら新規スクリプトに鍵を埋め込まずに済む

4. **CORS / CacheControl 指定**
   - GPTsからフェッチされるため、`Cache-Control: public, max-age=3600` を推奨
   - CORS はR2のバケット側で設定する(コード側ではなくダッシュボード)。現状設定は **不明**

5. **実行時間の見込み**
   - 292MB の読み込み: 約10〜30秒(ディスク次第)
   - 血統集計(39,674頭 × 5レース): 約5〜15秒
   - R2アップロード: 各100KB × 3 = 数秒
   - 合計: **1〜2分程度**で完了する見込み

6. **ローカル出力ディレクトリ**
   - `out/` ディレクトリか `./` 直下か。一回限りなら scripts/ 直下か scripts/out/ で十分
