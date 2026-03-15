-- migrate_mybot_public.sql
-- Supabase migration: mybot public profile, follows, login history
-- Safe idempotent execution using DO $$ blocks

-- 1. Add catchphrase and self_introduction to mybot_settings
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'mybot_settings' AND column_name = 'catchphrase'
    ) THEN
        ALTER TABLE mybot_settings ADD COLUMN catchphrase TEXT DEFAULT '';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'mybot_settings' AND column_name = 'self_introduction'
    ) THEN
        ALTER TABLE mybot_settings ADD COLUMN self_introduction TEXT DEFAULT '';
    END IF;
END $$;

-- 2. Add x_account and icon_url to user_profiles
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'user_profiles' AND column_name = 'x_account'
    ) THEN
        ALTER TABLE user_profiles ADD COLUMN x_account TEXT DEFAULT '';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'user_profiles' AND column_name = 'icon_url'
    ) THEN
        ALTER TABLE user_profiles ADD COLUMN icon_url TEXT DEFAULT NULL;
    END IF;
END $$;

-- 3. Create mybot_follows table
CREATE TABLE IF NOT EXISTS mybot_follows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    bot_user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, bot_user_id)
);

-- 4. Create login_history table
CREATE TABLE IF NOT EXISTS login_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    logged_in_at TIMESTAMPTZ DEFAULT now(),
    ip_address TEXT DEFAULT '',
    user_agent TEXT DEFAULT ''
);
