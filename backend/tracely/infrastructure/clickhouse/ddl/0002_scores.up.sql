-- Tracely `scores`: the verdict/measurement sink (Langfuse scores + Tracely deltas).
-- data_type is the Langfuse set (NUMERIC|CATEGORICAL|BOOLEAN|CORRECTION|TEXT) — NO PASS_FAIL;
-- gate/regression results use BOOLEAN value + the first-class `verdict` column. (canonical §3/§5)
CREATE TABLE IF NOT EXISTS scores
(
    project_id      String,
    id              String,

    -- addressing (any level): a score targets a trace/span/session/run/turn
    trace_id        Nullable(String),
    observation_id  Nullable(String),
    session_id      Nullable(String),
    agent_run_id    String DEFAULT '',
    turn_id         String DEFAULT '',

    name            String,
    source          LowCardinality(String),               -- API|EVAL|ANNOTATION
    data_type       LowCardinality(String),               -- NUMERIC|CATEGORICAL|BOOLEAN|CORRECTION|TEXT
    value           Nullable(Float64),
    string_value    String DEFAULT '',

    verdict           LowCardinality(String) DEFAULT '',  -- PASS|FAIL|SKIP
    evaluation_case_id String DEFAULT '',
    gate_run_id        String DEFAULT '',
    evaluation_level   LowCardinality(String) DEFAULT '',
    execution_trace_id String DEFAULT '',                 -- evals are themselves traced

    comment   String DEFAULT '',
    metadata  Map(LowCardinality(String), String),

    event_ts   DateTime64(6) DEFAULT now64(6),
    is_deleted UInt8 DEFAULT 0,
    created_at DateTime64(6) DEFAULT now64(6),

    INDEX idx_scores_gate_run  gate_run_id        TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_scores_eval_case evaluation_case_id TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(event_ts, is_deleted)
PARTITION BY toYYYYMM(created_at)
ORDER BY (project_id, name, id)
-- Retention: scores age out 90 days after they were written (same horizon as `events`). Tune via
-- 0004_scores_ttl (ALTER MODIFY TTL).
TTL toDateTime(created_at) + INTERVAL 90 DAY
SETTINGS index_granularity = 8192
