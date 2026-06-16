-- Apply the 90-day retention TTL to an EXISTING `events` table (the CREATE in 0001 only takes
-- effect on a fresh table — it's IF NOT EXISTS). ALTER ... MODIFY TTL is idempotent: re-running it
-- with the same expression is a no-op, so this is safe to apply on every migrate.
ALTER TABLE events MODIFY TTL toDateTime(start_time) + INTERVAL 90 DAY
