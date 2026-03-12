-- ============================================================
-- Dlogic Bot - Supabase Phase 2 テーブル定義
-- ============================================================

-- 1. ユーザープロフィール
CREATE TABLE user_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  line_user_id TEXT UNIQUE NOT NULL,
  display_name TEXT,

  -- 構造化プロフィール（Claudeが会話から自動更新）
  favorite_venues TEXT[] DEFAULT '{}',
  favorite_horses TEXT[] DEFAULT '{}',
  favorite_jockeys TEXT[] DEFAULT '{}',
  bet_style TEXT DEFAULT '',
  risk_level TEXT DEFAULT '',
  experience_level TEXT DEFAULT '',

  -- 統計
  visit_count INT DEFAULT 0,
  total_predictions INT DEFAULT 0,
  first_seen_at TIMESTAMPTZ DEFAULT now(),
  last_seen_at TIMESTAMPTZ DEFAULT now()
);

-- 2. 自由メモリ（会話から抽出した記憶）
CREATE TABLE user_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_profile_id UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
  category TEXT DEFAULT 'general',
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. 予想リクエスト履歴（将来のポイント制基盤）
CREATE TABLE prediction_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_profile_id UUID REFERENCES user_profiles(id) ON DELETE CASCADE,
  race_id TEXT NOT NULL,
  race_name TEXT,
  venue TEXT,
  requested_at TIMESTAMPTZ DEFAULT now()
);

-- インデックス
CREATE INDEX idx_user_profiles_line ON user_profiles(line_user_id);
CREATE INDEX idx_user_memories_profile ON user_memories(user_profile_id);
CREATE INDEX idx_user_memories_category ON user_memories(user_profile_id, category);
CREATE INDEX idx_prediction_history_profile ON prediction_history(user_profile_id);
CREATE INDEX idx_prediction_history_race ON prediction_history(race_id);

-- RLS (Row Level Security) は service_role キーで操作するため無効
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE prediction_history ENABLE ROW LEVEL SECURITY;

-- service_role はRLSをバイパスするのでポリシー不要
-- anon キーからのアクセスは全拒否（デフォルト）
