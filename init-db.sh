#!/bin/bash
set -e

echo "Starting database initialization for messages database..."

# Create tables in messages database (same database that Airflow will use)
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Application tables
    CREATE TABLE IF NOT EXISTS messages (
        message_id SERIAL PRIMARY KEY,
        content TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        used BOOLEAN DEFAULT FALSE,
        used_time TIMESTAMP,
        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Drop and recreate tweets_scraped table with proper auto-incrementing tweet_id
    DROP TABLE IF EXISTS tweets_scraped CASCADE;
    CREATE TABLE tweets_scraped (
        tweet_id SERIAL PRIMARY KEY,  -- Changed from TEXT to SERIAL
        link TEXT NOT NULL,
        scraped_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- Added default
        user_id INTEGER DEFAULT 0,  -- Added default since it's NOT NULL
        used BOOLEAN DEFAULT FALSE,
        used_time TIMESTAMP,
        follow BOOLEAN DEFAULT FALSE,
        message BOOLEAN DEFAULT FALSE,
        reply BOOLEAN DEFAULT FALSE,
        retweet BOOLEAN DEFAULT FALSE
    );

    CREATE TABLE IF NOT EXISTS workflow_runs (
        id SERIAL PRIMARY KEY,
        workflow_name TEXT NOT NULL,
        run_id TEXT NOT NULL,
        status TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS processed_tweets (
        id SERIAL PRIMARY KEY,
        tweet_id TEXT NOT NULL UNIQUE,
        processed_time TIMESTAMP NOT NULL,
        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS workflow_generation_log (
        id SERIAL PRIMARY KEY,
        workflow_name TEXT NOT NULL,
        generated_time TIMESTAMP NOT NULL,
        tweet_id TEXT,
        message_id INTEGER,
        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS workflow_limits (
        id SERIAL PRIMARY KEY,
        limit_type TEXT NOT NULL UNIQUE,
        max_count INTEGER NOT NULL,
        current_count INTEGER DEFAULT 0,
        reset_time TIMESTAMP NOT NULL,
        created_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Insert default workflow limits
    INSERT INTO workflow_limits (limit_type, max_count, reset_time)
    VALUES 
        ('daily', 6, NOW() + INTERVAL '1 day'),
        ('hourly', 2, NOW() + INTERVAL '1 hour')
    ON CONFLICT (limit_type) DO NOTHING;

    -- Create indexes for better performance
    CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);
    CREATE INDEX IF NOT EXISTS idx_messages_used ON messages(used);
    CREATE INDEX IF NOT EXISTS idx_tweets_scraped_user_id ON tweets_scraped(user_id);
    CREATE INDEX IF NOT EXISTS idx_tweets_scraped_used ON tweets_scraped(used);
    CREATE INDEX IF NOT EXISTS idx_tweets_scraped_link ON tweets_scraped(link);  -- Added for CONFLICT handling
    CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_name ON workflow_runs(workflow_name);
    CREATE INDEX IF NOT EXISTS idx_workflow_runs_status ON workflow_runs(status);
    CREATE INDEX IF NOT EXISTS idx_processed_tweets_tweet_id ON processed_tweets(tweet_id);
    CREATE INDEX IF NOT EXISTS idx_workflow_limits_limit_type ON workflow_limits(limit_type);

EOSQL

echo "Database initialization completed successfully!"
echo "All tables created in 'messages' database - ready for both Airflow and application use."