-- Tracely `events`: one immutable row per span (Langfuse events_full + Tracely first-class
-- agent columns; prompt_*/experiment_* dropped). ReplacingMergeTree gives upsert/soft-delete.
CREATE TABLE IF NOT EXISTS events
(
    project_id      String,
    trace_id        String,
    span_id         String,
    parent_span_id  String,

    start_time              DateTime64(6),
    end_time                Nullable(DateTime64(6)),
    completion_start_time   Nullable(DateTime64(6)),

    name            String,
    type            LowCardinality(String),
    environment     LowCardinality(String) DEFAULT 'default',
    env             LowCardinality(String) DEFAULT 'prod',     -- gating axis: prod|staging|ci|dev
    version         String DEFAULT '',
    release         String DEFAULT '',
    level           LowCardinality(String) DEFAULT 'DEFAULT',
    status_message  String DEFAULT '',
    is_app_root     Bool   DEFAULT false,

    trace_name      String DEFAULT '',
    user_id         String DEFAULT '',
    session_id      String DEFAULT '',
    tags            Array(String) DEFAULT [],

    -- first-class agent semantics (NOT metadata strings)
    agent_id          String DEFAULT '',
    agent_version_id  String DEFAULT '',
    agent_run_id      String DEFAULT '',
    conversation_id   String DEFAULT '',
    turn_id           String DEFAULT '',
    turn_index        UInt32 DEFAULT 0,
    step_id           String DEFAULT '',
    step_name         String DEFAULT '',

    -- typed edges (inline common cases)
    tool_call_id     String DEFAULT '',
    caller_agent_id  String DEFAULT '',
    callee_agent_id  String DEFAULT '',
    edge_type        LowCardinality(String) DEFAULT '',

    -- provenance
    evaluation_case_id  String DEFAULT '',
    gate_run_id         String DEFAULT '',
    failure_cluster_id  String DEFAULT '',

    -- model / usage / cost
    model_id         String DEFAULT '',
    model_parameters String DEFAULT '',
    usage_details    Map(LowCardinality(String), UInt64),
    cost_details     Map(LowCardinality(String), Decimal(18, 12)),

    -- tools
    tool_definitions Map(String, String),
    tool_calls       Array(String) DEFAULT [],
    tool_call_names  Array(String) DEFAULT [],

    -- io + metadata
    input    Nullable(String) CODEC(ZSTD(3)),
    output   Nullable(String) CODEC(ZSTD(3)),
    metadata Map(LowCardinality(String), String),

    -- instrumentation provenance
    source                 LowCardinality(String) DEFAULT 'otel',
    service_name           String DEFAULT '',
    scope_name             String DEFAULT '',
    telemetry_sdk_language String DEFAULT '',
    telemetry_sdk_name     String DEFAULT '',
    telemetry_sdk_version  String DEFAULT '',

    -- bookkeeping (ReplacingMergeTree)
    event_ts   DateTime64(6) DEFAULT now64(6),
    is_deleted UInt8 DEFAULT 0,
    created_at DateTime64(6) DEFAULT now64(6),

    INDEX idx_agent_id        agent_id        TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_agent_run_id    agent_run_id    TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_conversation_id conversation_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_gate_run_id     gate_run_id     TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_eval_case_id    evaluation_case_id TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(event_ts, is_deleted)
PARTITION BY toYYYYMM(start_time)
ORDER BY (project_id, toStartOfMinute(start_time), xxHash32(trace_id), span_id, start_time)
SAMPLE BY xxHash32(trace_id)
-- Retention: drop spans 90 days after they happened so the single-volume ClickHouse can't grow
-- unbounded and fill its disk. Tune via 0003_events_ttl (ALTER MODIFY TTL) without a table rebuild.
TTL toDateTime(start_time) + INTERVAL 90 DAY
SETTINGS index_granularity = 8192
