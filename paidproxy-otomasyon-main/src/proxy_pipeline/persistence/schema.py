from __future__ import annotations

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
CREATE TABLE IF NOT EXISTS schema_migrations(
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS source_catalog(
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    source_type TEXT NOT NULL,
    connector TEXT NOT NULL,
    license_note TEXT NOT NULL,
    capability TEXT NOT NULL,
    quota TEXT NOT NULL,
    freshness_ms INTEGER,
    health TEXT NOT NULL,
    enabled INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS source_fetches(
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    request_fingerprint TEXT NOT NULL,
    cache_metadata TEXT NOT NULL,
    response_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_ms INTEGER,
    error TEXT,
    fetched_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS organizations(
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    aliases TEXT NOT NULL,
    country TEXT,
    network_role TEXT,
    resolution_confidence TEXT
);
CREATE TABLE IF NOT EXISTS asns(
    id INTEGER PRIMARY KEY,
    asn INTEGER UNIQUE NOT NULL,
    organization_id INTEGER,
    routing_summary TEXT,
    peeringdb_summary TEXT,
    caida_summary TEXT,
    first_seen INTEGER,
    last_seen INTEGER,
    aggregate_outcome TEXT
);
CREATE TABLE IF NOT EXISTS prefixes(
    id INTEGER PRIMARY KEY,
    network BLOB NOT NULL,
    prefix_length INTEGER NOT NULL,
    ip_version INTEGER NOT NULL,
    origin_asn INTEGER,
    advertised_state TEXT,
    first_seen INTEGER,
    last_seen INTEGER
);
CREATE TABLE IF NOT EXISTS prefix_sources(
    id INTEGER PRIMARY KEY,
    prefix_id INTEGER NOT NULL,
    source_record_id INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    payload_hash TEXT NOT NULL,
    confidence TEXT,
    conflict TEXT
);
CREATE TABLE IF NOT EXISTS candidate_contexts(
    id INTEGER PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'prefix',
    entity_id TEXT NOT NULL DEFAULT '',
    context_hash TEXT NOT NULL,
    payload_ref TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_modes(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    mode_type TEXT NOT NULL,
    graph_ref TEXT NOT NULL,
    version TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    created_by TEXT NOT NULL,
    activation_state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_routes(
    id INTEGER PRIMARY KEY,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    fallback_order INTEGER NOT NULL,
    config TEXT NOT NULL,
    health TEXT NOT NULL,
    version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_versions(
    id INTEGER PRIMARY KEY,
    version TEXT UNIQUE NOT NULL,
    prompt_ref TEXT NOT NULL,
    tool_set TEXT NOT NULL,
    retrieval_policy TEXT NOT NULL,
    objective TEXT NOT NULL,
    mode_version TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_decisions(
    id INTEGER PRIMARY KEY,
    decision_id TEXT UNIQUE NOT NULL,
    state TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    context_snapshot_id INTEGER,
    prompt_payload_ref TEXT,
    prompt_hash TEXT,
    raw_response_ref TEXT,
    raw_response_hash TEXT,
    parsed_action TEXT,
    plan_summary TEXT,
    evidence_summary TEXT,
    confidence TEXT,
    provider TEXT,
    model TEXT,
    mode_version TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    prompt_version TEXT,
    tool_version TEXT,
    parent_decision_id TEXT,
    superseded_by TEXT,
    schema_result TEXT,
    inference_ms INTEGER,
    token_count INTEGER,
    cost TEXT,
    created_at INTEGER NOT NULL,
    committed_at INTEGER,
    executed_at INTEGER
);
CREATE TABLE IF NOT EXISTS decision_items(
    id INTEGER PRIMARY KEY,
    decision_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    target TEXT NOT NULL,
    action TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    resource_allocation TEXT NOT NULL,
    stop_expression TEXT NOT NULL,
    reassessment_expression TEXT,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_manifests(
    id INTEGER PRIMARY KEY,
    manifest_id TEXT UNIQUE NOT NULL,
    decision_id TEXT NOT NULL,
    payload_ref TEXT NOT NULL,
    target_intent TEXT NOT NULL,
    technical_profile TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_runs(
    id INTEGER PRIMARY KEY,
    run_id TEXT UNIQUE NOT NULL,
    manifest_id TEXT NOT NULL,
    started_at INTEGER,
    finished_at INTEGER,
    scanner_profile TEXT NOT NULL,
    state TEXT NOT NULL,
    counters TEXT NOT NULL,
    stop_reason TEXT
);
CREATE TABLE IF NOT EXISTS scan_segments(
    id INTEGER PRIMARY KEY,
    segment_id TEXT UNIQUE NOT NULL,
    manifest_id TEXT NOT NULL,
    path TEXT NOT NULL,
    checksum TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    cursor INTEGER NOT NULL,
    lease_owner TEXT,
    lease_until INTEGER,
    retry_count INTEGER NOT NULL,
    state TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    completed_at INTEGER
);
CREATE TABLE IF NOT EXISTS endpoints(
    id INTEGER PRIMARY KEY,
    ip_binary BLOB NOT NULL,
    port INTEGER NOT NULL,
    current_state TEXT NOT NULL,
    first_seen INTEGER,
    last_seen INTEGER,
    last_validation INTEGER,
    protocol_summary TEXT,
    active_confidence TEXT,
    UNIQUE(ip_binary,port)
);
CREATE TABLE IF NOT EXISTS validations(
    id INTEGER PRIMARY KEY,
    endpoint_id INTEGER NOT NULL,
    protocol TEXT NOT NULL,
    result TEXT NOT NULL,
    reason TEXT NOT NULL,
    latency_ms REAL,
    echo_ref TEXT,
    attempt INTEGER NOT NULL,
    manifest_id TEXT,
    decision_id TEXT,
    run_id TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS exit_observations(
    id INTEGER PRIMARY KEY,
    endpoint_id INTEGER NOT NULL,
    exit_ip_binary BLOB NOT NULL,
    exit_asn INTEGER,
    country TEXT,
    ip_version INTEGER NOT NULL,
    echo_region TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    observed_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS asset_assessments(
    id INTEGER PRIMARY KEY,
    endpoint_id INTEGER NOT NULL,
    classification TEXT NOT NULL,
    confidence TEXT NOT NULL,
    sample_size INTEGER NOT NULL,
    window_ms INTEGER NOT NULL,
    diversity TEXT NOT NULL,
    evidence_refs TEXT NOT NULL,
    classifier_version TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS state_events(
    id INTEGER PRIMARY KEY,
    event_id TEXT UNIQUE,
    event_type TEXT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    reason TEXT,
    decision_id TEXT,
    manifest_id TEXT,
    correlation_id TEXT,
    causation_id TEXT,
    actor TEXT,
    payload TEXT,
    occurred_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS decision_outcomes(
    id INTEGER PRIMARY KEY,
    decision_id TEXT NOT NULL,
    item_id TEXT,
    outcome TEXT NOT NULL,
    cost TEXT,
    duration_ms INTEGER,
    regret TEXT,
    evaluator TEXT,
    user_feedback TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS operator_feedback(
    id INTEGER PRIMARY KEY,
    decision_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    approval TEXT NOT NULL,
    correction TEXT,
    reason TEXT,
    before_action TEXT,
    after_action TEXT,
    training_eligible INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    mode_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    cohort TEXT NOT NULL,
    objective TEXT NOT NULL,
    evaluation_set TEXT NOT NULL,
    result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limit_buckets(
    id INTEGER PRIMARY KEY,
    bucket_key TEXT UNIQUE NOT NULL,
    capacity REAL NOT NULL,
    tokens REAL NOT NULL,
    refill_rate REAL NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts(
    id INTEGER PRIMARY KEY,
    severity TEXT NOT NULL,
    source TEXT NOT NULL,
    dedupe_key TEXT UNIQUE NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    count INTEGER NOT NULL,
    status TEXT NOT NULL,
    acknowledged_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_prefixes_asn ON prefixes(origin_asn,advertised_state);
CREATE INDEX IF NOT EXISTS idx_prefix_sources_obs ON prefix_sources(prefix_id,observed_at);
CREATE INDEX IF NOT EXISTS idx_contexts_entity ON candidate_contexts(entity_type,entity_id,created_at);
CREATE INDEX IF NOT EXISTS idx_contexts_candidate ON candidate_contexts(candidate_id,created_at);
CREATE INDEX IF NOT EXISTS idx_decisions_state ON agent_decisions(state,decision_type,created_at);
CREATE INDEX IF NOT EXISTS idx_decisions_context ON agent_decisions(context_hash,strategy_version,mode_version);
CREATE INDEX IF NOT EXISTS idx_items_decision ON decision_items(decision_id,status,order_index);
CREATE INDEX IF NOT EXISTS idx_manifests_status ON execution_manifests(status,created_at);
CREATE INDEX IF NOT EXISTS idx_segments_lease ON scan_segments(state,lease_until);
CREATE INDEX IF NOT EXISTS idx_endpoints_ip_port ON endpoints(ip_binary,port);
CREATE INDEX IF NOT EXISTS idx_validations_endpoint ON validations(endpoint_id,created_at);
CREATE INDEX IF NOT EXISTS idx_events_entity ON state_events(entity_type,entity_id,occurred_at);
CREATE INDEX IF NOT EXISTS idx_outcomes_decision ON decision_outcomes(decision_id,created_at);
"""
