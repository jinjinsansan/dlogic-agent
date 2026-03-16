-- MYBOT Recovery Rate Tracking
-- Run on Supabase SQL Editor

-- 1. MYBOT predictions log (auto-recorded when MYBOT makes a prediction)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mybot_predictions') THEN
    CREATE TABLE mybot_predictions (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      bot_user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
      race_id TEXT NOT NULL,
      race_name TEXT,
      venue TEXT,
      s_rank_horse_number INTEGER NOT NULL,
      s_rank_horse_name TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE(bot_user_id, race_id)
    );
    CREATE INDEX idx_mybot_predictions_race ON mybot_predictions(race_id);
    CREATE INDEX idx_mybot_predictions_bot ON mybot_predictions(bot_user_id);
  END IF;
END $$;

-- 2. MYBOT stats (aggregated recovery rate)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'mybot_stats') THEN
    CREATE TABLE mybot_stats (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      bot_user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
      total_predictions INTEGER NOT NULL DEFAULT 0,
      total_wins INTEGER NOT NULL DEFAULT 0,
      total_payout INTEGER NOT NULL DEFAULT 0,
      recovery_rate FLOAT NOT NULL DEFAULT 0,
      win_rate FLOAT NOT NULL DEFAULT 0,
      last_updated_at TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE(bot_user_id)
    );
  END IF;
END $$;
