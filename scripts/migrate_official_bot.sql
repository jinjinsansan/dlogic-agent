-- migrate_official_bot.sql
-- Supabase migration: Create official Dlogic bot profile for FK constraints
-- Required for mybot_follows to work with DLOGIC_OFFICIAL_BOT_ID
-- Safe idempotent execution

-- 1. Create official Dlogic bot profile (needed for mybot_follows FK)
INSERT INTO user_profiles (id, line_user_id, display_name, custom_name, visit_count, status)
VALUES (
    '00000000-0000-0000-0000-000000000000',
    'dlogic_official',
    'Dlogic公式',
    TRUE,
    0,
    'active'
)
ON CONFLICT (id) DO NOTHING;

-- 2. Create mybot_settings for official Dlogic bot (needed for public bot page)
INSERT INTO mybot_settings (user_id, bot_name, personality, tone, description, catchphrase, self_introduction, is_public, chat_theme, horse_weight, jockey_weight)
VALUES (
    '00000000-0000-0000-0000-000000000000',
    'Dロジくん',
    'energetic',
    'casual',
    'Dlogic公式の競馬AI予想ボット。4つの独自エンジンで予想を提供します。',
    '競馬AIの力、見せてやるぜ！',
    'オレはDロジくん！Dlogicの公式AIボットだ。独自の4エンジンで競馬予想をぶちかますぜ！',
    TRUE,
    'default',
    30,
    20
)
ON CONFLICT (user_id) DO NOTHING;
