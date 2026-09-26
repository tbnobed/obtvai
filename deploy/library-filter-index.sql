-- Run with psql outside a transaction; safe for a live archive.
-- Also included in the explicit archive_memory migration for future installs.
-- Concurrent builds may wait for old slow filter queries to release snapshots.
-- This bounds that wait without taking a lock that blocks ordinary writes.
SET lock_timeout = '120s';
SET statement_timeout = '5min';
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_catalog_media_type
  ON curator_catalog_assets (media_id, asset_type);
ANALYZE curator_catalog_assets;