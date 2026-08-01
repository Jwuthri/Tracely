-- Internal runs: Tracely's own work (evaluating a trace, driving a scenario) recorded AS a trace,
-- so the judge prompt / attacker move / endpoint call are debuggable with the tools that already
-- exist instead of grep on worker logs.
--
-- `internal_kind` is the hide-by-default axis AND the infinite-loop guard: a trace with a non-empty
-- kind is never scheduled for evaluation, because evaluating an eval run would record another eval
-- run, forever. `subject_id` is the trace or conversation the run is about — how the UI finds
-- "the eval for THIS trace" without polluting conversation_id/session_id (which the session views
-- group by, and which would make eval spans show up as turns).
--
-- One statement (comma-separated actions), per the runner's one-statement-per-file convention.
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS internal_kind LowCardinality(String) DEFAULT '',
    ADD COLUMN IF NOT EXISTS subject_id String DEFAULT '',
    ADD INDEX IF NOT EXISTS idx_subject_id subject_id TYPE bloom_filter(0.01) GRANULARITY 1
