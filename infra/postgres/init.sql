-- PostgreSQL initialization script
-- Creates extensions, sets up proper permissions

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create read-only user for monitoring/backups
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'monitoring') THEN
        CREATE ROLE monitoring WITH LOGIN PASSWORD '${MONITORING_PASSWORD}';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE ${DB_NAME} TO monitoring;
GRANT USAGE ON SCHEMA public TO monitoring;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO monitoring;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO monitoring;

-- Create backup user
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'backup_user') THEN
        CREATE ROLE backup_user WITH LOGIN PASSWORD '${BACKUP_PASSWORD}';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE ${DB_NAME} TO backup_user;
GRANT USAGE ON SCHEMA public TO backup_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO backup_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO backup_user;

-- Set timezone
SET timezone = 'UTC';

-- Performance settings (applied per session)
ALTER DATABASE ${DB_NAME} SET timezone = 'UTC';
ALTER DATABASE ${DB_NAME} SET statement_timeout = '30s';
ALTER DATABASE ${DB_NAME} SET lock_timeout = '10s';
ALTER DATABASE ${DB_NAME} SET idle_in_transaction_session_timeout = '60s';