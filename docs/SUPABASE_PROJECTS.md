# Supabase プロジェクト対応表(混同防止)

> 複数のSupabaseプロジェクトが存在し、どのサービスがどれを使うか紛らわしいので明記。
> 作成: 2026-06-04。**SQL実行・キー設定の前に必ずこの表でプロジェクトを確認すること。**
> (過去に nk_* テーブルを誤って別プロジェクトに作成する事故あり)

## 3つのプロジェクト

| Project Ref (ID) | サービス | 主なテーブル / 用途 |
|---|---|---|
| **`agkuvhiycthrloxzhgjc`** | **LINE Bot(Dlogic)+ オッズ監視(オッズ急落くん)** | `user_profiles`, `user_memories`, `prediction_history`(ユーザー管理) / `odds_signals`, `odds_snapshots`, `race_results`(オッズ急変。monitorが書込→急落くんが読込) |
| **`vhzqojlpldiewnlatqww`** | **netkeita**(記事/予想サイト) | `users` / `nk_articles`, `nk_tipsters`, `nk_kreward`, `nk_kreward_log`, `nk_votes`(2026-06-04 永続化で追加) |
| **`veklxmosegqkjtvjbksd`** | **予想backend**(FastAPI 予想エンジン :8000) | backend用 |

## どのサービスがどのプロジェクトを使うか

| サービス / 場所 | .env の SUPABASE_URL | プロジェクト |
|---|---|---|
| LINE Bot `/opt/dlogic/linebot` | `agkuvhiycthrloxzhgjc` | LINE Bot + オッズ |
| オッズ監視 `/opt/dlogic/odds-monitor` | `agkuvhiycthrloxzhgjc` | 同上(odds_signals 書込) |
| **オッズ急落くん** `dlogic-odds-monitor/frontend` | `agkuvhiycthrloxzhgjc` | 同上(odds_* 読込) |
| netkeita-api `/opt/dlogic/netkeita-api` | `vhzqojlpldiewnlatqww` | netkeita |
| 予想backend `/opt/dlogic/backend` | `veklxmosegqkjtvjbksd` | backend |

## よくある混同(注意)
- ❌「agkuvhiycthrloxzhgjc = netkeita」→ **違う**。agku… は LINE Bot + オッズ。netkeita は `vhzqojlpldiewnlatqww`。
- netkeitaのSQL(nk_articles等)は必ず **`vhzqojlpldiewnlatqww`** で実行する(過去に agku… に誤実行した)。
- **オッズ急落くんが読むのは `agkuvhiycthrloxzhgjc`**(オッズ急変データがそこにあるため。netkeitaではない)。

## キーの所在
- 各サービスの `.env` / `.env.local`(VPS上、gitignore)に SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY。
- service_role キーは各プロジェクトごとに異なる(JWTの `ref` で判別可: `key.split('.')[1]` をbase64デコード→`ref`)。

---
_関連: [[project_odds_kyuraku]](急落くん), netkeita永続化(nk_*テーブル)。_
