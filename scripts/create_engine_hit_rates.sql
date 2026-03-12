-- Engine hit-rate tracking table
CREATE TABLE IF NOT EXISTS engine_hit_rates (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date DATE NOT NULL,
    race_id TEXT NOT NULL,
    venue TEXT NOT NULL,
    race_number INT NOT NULL,
    race_type TEXT NOT NULL,  -- 'jra' or 'nar'
    engine TEXT NOT NULL,     -- 'dlogic', 'ilogic', 'viewlogic', 'metalogic'
    top1_horse INT NOT NULL,
    top3_horses INT[] NOT NULL,
    result_1st INT NOT NULL,
    result_2nd INT NOT NULL,
    result_3rd INT NOT NULL,
    hit_win BOOLEAN NOT NULL DEFAULT FALSE,
    hit_place BOOLEAN NOT NULL DEFAULT FALSE,
    place_hit_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(race_id, engine)
);

-- Index for date-range queries
CREATE INDEX IF NOT EXISTS idx_engine_hit_rates_date ON engine_hit_rates(date);
CREATE INDEX IF NOT EXISTS idx_engine_hit_rates_engine ON engine_hit_rates(engine);
