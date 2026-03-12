-- みんなの予想 — Phase 1-5 テーブル作成
-- Supabase SQL Editor で実行

-- Phase 1: ユーザー予想記録
CREATE TABLE IF NOT EXISTS user_predictions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_profile_id uuid NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    race_id text NOT NULL,
    horse_number integer NOT NULL,
    horse_name text NOT NULL,
    race_name text DEFAULT '',
    venue text DEFAULT '',
    race_date date,
    race_type text DEFAULT 'jra',
    created_at timestamptz DEFAULT now(),
    UNIQUE(user_profile_id, race_id)
);

CREATE INDEX IF NOT EXISTS idx_user_predictions_race_id ON user_predictions(race_id);
CREATE INDEX IF NOT EXISTS idx_user_predictions_user ON user_predictions(user_profile_id);
CREATE INDEX IF NOT EXISTS idx_user_predictions_date ON user_predictions(race_date);

-- Phase 2: レース結果
CREATE TABLE IF NOT EXISTS race_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    race_id text UNIQUE NOT NULL,
    race_name text DEFAULT '',
    venue text DEFAULT '',
    race_date date,
    race_type text DEFAULT 'jra',
    winner_number integer,
    winner_name text DEFAULT '',
    win_payout integer DEFAULT 0,
    result_json jsonb,
    status text DEFAULT 'pending',
    fetched_at timestamptz,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_race_results_date ON race_results(race_date);
CREATE INDEX IF NOT EXISTS idx_race_results_status ON race_results(status);

-- Phase 3: ユーザー成績キャッシュ
CREATE TABLE IF NOT EXISTS user_stats (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_profile_id uuid UNIQUE NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    total_picks integer DEFAULT 0,
    total_wins integer DEFAULT 0,
    total_payout integer DEFAULT 0,
    total_bet integer DEFAULT 0,
    recovery_rate float DEFAULT 0,
    win_rate float DEFAULT 0,
    current_streak integer DEFAULT 0,
    best_payout integer DEFAULT 0,
    last_updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_stats_recovery ON user_stats(recovery_rate DESC);
CREATE INDEX IF NOT EXISTS idx_user_stats_picks ON user_stats(total_picks);

-- Phase 5: ポイント残高
CREATE TABLE IF NOT EXISTS user_points (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_profile_id uuid UNIQUE NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    balance integer DEFAULT 0,
    total_purchased integer DEFAULT 0,
    total_spent integer DEFAULT 0,
    created_at timestamptz DEFAULT now()
);

-- Phase 5: ポイント取引履歴
CREATE TABLE IF NOT EXISTS point_transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_profile_id uuid NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    amount integer NOT NULL,
    type text NOT NULL,
    description text DEFAULT '',
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_point_transactions_user ON point_transactions(user_profile_id);
