"""SQL query templates and helpers for querying AI Gateway inference tables.

Each model service writes to its own inference table, named
`<catalog>.<schema>.<service-name>_payload`. The prefix is the *service* name,
and the table may live in a different schema than the service itself — so the
fully-qualified table is passed in explicitly rather than derived. Read it from
`gateway_config.fetch_service_config()['inference_table']`.

NOTE: guardrail-blocked requests do NOT appear in these tables. A request denied
by a service policy is rejected before it reaches the model, and the inference
table records model invocations — so only requests that reached a model are
logged. The record of what was blocked is the `databricks_service_policy` in the
response (see `agent_simulator.detect_policy_block`) and the MLflow traces.
"""

ALL_REQUESTS_QUERY = """
SELECT
    event_time,
    request_id,
    status_code,
    requester,
    latency_ms,
    request,
    response
FROM {table}
ORDER BY event_time DESC
LIMIT {limit}
"""

# Transport / backend failures — e.g. a guardrail judge briefly unavailable (500).
# This is NOT the guardrail-block query: policy denials never reach the table.
FAILED_REQUESTS_QUERY = """
SELECT
    event_time,
    request_id,
    status_code,
    requester,
    latency_ms,
    request,
    logging_error_codes
FROM {table}
WHERE status_code != 200
   OR (logging_error_codes IS NOT NULL AND size(logging_error_codes) > 0)
ORDER BY event_time DESC
LIMIT {limit}
"""

# Every row here reached a model (policy denials aren't logged), so the split is
# succeeded vs. failed — not allowed vs. blocked.
TOKEN_USAGE_QUERY = """
SELECT
    CASE WHEN status_code = 200 THEN 'succeeded' ELSE 'failed' END AS outcome,
    COUNT(*)                                                        AS request_count,
    SUM(CAST(response:usage:total_tokens      AS BIGINT))          AS total_tokens,
    SUM(CAST(response:usage:prompt_tokens     AS BIGINT))          AS input_tokens,
    SUM(CAST(response:usage:completion_tokens AS BIGINT))          AS output_tokens,
    ROUND(AVG(latency_ms), 0)                                      AS avg_latency_ms
FROM {table}
WHERE event_time >= CURRENT_TIMESTAMP - INTERVAL 1 HOUR
GROUP BY 1
ORDER BY total_tokens DESC NULLS LAST
LIMIT {limit}
"""

# Billing-grade hourly aggregates, spanning every model service. Model services
# appear here with service_type = 'MODEL_SERVICE' and endpoint_name /
# service_name set to the fully-qualified UC name. Note the time column is
# `event_time` (not `usage_time`).
SYSTEM_USAGE_QUERY = """
SELECT
    endpoint_name,
    DATE_TRUNC('hour', event_time)    AS hour,
    COUNT(*)                          AS request_count,
    SUM(input_tokens)                 AS input_tokens,
    SUM(output_tokens)                AS output_tokens,
    SUM(total_tokens)                 AS total_tokens
FROM system.ai_gateway.usage
WHERE endpoint_name IN ({endpoint_names})
  AND event_time >= CURRENT_TIMESTAMP - INTERVAL 1 HOUR
GROUP BY endpoint_name, DATE_TRUNC('hour', event_time)
ORDER BY hour DESC, total_tokens DESC
"""

QUERY_MAP = {
    "all": ALL_REQUESTS_QUERY,
    "failed": FAILED_REQUESTS_QUERY,
    "token_usage": TOKEN_USAGE_QUERY,
    "system_usage": SYSTEM_USAGE_QUERY,
}


def quote_table(table: str) -> str:
    """Backtick-quote each part of a fully-qualified table name.

    Inference-table names contain hyphens (the service name is the prefix), so
    every identifier has to be quoted to be valid SQL.
    """
    return ".".join(f"`{part.strip('`')}`" for part in table.split("."))


def build_query(
    query_name: str,
    table: str = "",
    limit: int = 50,
    endpoint_names: list[str] | None = None,
    **kwargs,
) -> str:
    """Return a formatted SQL query string.

    `table` is the fully-qualified inference table (from
    `fetch_service_config`). `endpoint_names` is used by the `system_usage`
    query to span every model service.
    """
    template = QUERY_MAP[query_name]
    if endpoint_names:
        kwargs["endpoint_names"] = ", ".join(f"'{n}'" for n in endpoint_names)
    return template.format(table=quote_table(table) if table else "", limit=limit, **kwargs)


def query_inference_table(spark, table: str, query_name: str = "all", limit: int = 50):
    """Execute a query against one service's inference table, returning a DataFrame."""
    sql = build_query(query_name, table=table, limit=limit)
    return spark.sql(sql)
