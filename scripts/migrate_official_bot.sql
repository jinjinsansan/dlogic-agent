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
