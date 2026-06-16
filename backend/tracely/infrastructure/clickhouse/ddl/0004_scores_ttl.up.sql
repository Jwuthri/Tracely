-- Apply the 90-day retention TTL to an EXISTING `scores` table (see 0003 for the rationale).
ALTER TABLE scores MODIFY TTL toDateTime(created_at) + INTERVAL 90 DAY
