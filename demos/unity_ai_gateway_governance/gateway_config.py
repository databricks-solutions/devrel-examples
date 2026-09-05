"""Unity AI Gateway configuration helpers.

Model services are configured through the Databricks UI. This module verifies
connectivity and reads back each service's *actual* configuration — guardrail
policies, routed model, inference table, rate limits — from Unity Catalog, so
the notebook reports what is really deployed rather than what we assume.
"""

import time
from dataclasses import dataclass, field

import requests as http_requests

# Retry transient rate-limit / server / guardrail-backend failures. A real
# guardrail block is 400 and is never retried.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
INITIAL_BACKOFF = 2


@dataclass
class GatewayConfig:
    endpoint_name: str
    models: list[str]
    catalog_name: str
    schema_name: str
    table_name_prefix: str = "coding_agents"

    # Fully-qualified Unity Catalog name of the model service
    # (`catalog.schema.service`) — the value sent in the request's `model` field.
    model_service: str = ""
    provider: str = ""

    pii_behavior: str = "BLOCK"
    safety_enabled: bool = True
    invalid_keywords: list = field(default_factory=list)
    valid_topics: list = field(default_factory=list)

    inference_table_enabled: bool = True
    usage_tracking_enabled: bool = True


def verify_gateway(host: str, token: str, model_service: str) -> dict:
    """Send a lightweight request to verify a governed model service is reachable.

    Every model service is reached through the one gateway URL; the service is
    selected by the `model` field carrying its fully-qualified UC name.
    """
    url = f"{host.rstrip('/')}/ai-gateway/mlflow/v1/chat/completions"
    backoff = INITIAL_BACKOFF
    resp = None
    for attempt in range(MAX_RETRIES):
        resp = http_requests.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": model_service,
                "messages": [{"role": "user", "content": "Say ok"}],
                "max_tokens": 5,
            },
            timeout=30,
        )
        if resp.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES - 1:
            time.sleep(backoff)
            backoff *= 2
            continue
        break
    result = {"status": resp.status_code, "reachable": resp.status_code == 200}
    if not result["reachable"]:
        result["error"] = resp.text[:300]
    return result


def fetch_service_config(host: str, token: str, model_service: str) -> dict:
    """Read a model service's deployed configuration from Unity Catalog.

    Returns the guardrail policies, the model traffic is routed to, the
    inference table actually being written to, and the rate-limit / usage-
    tracking settings. `error` is set if the service can't be read.
    """
    url = f"{host.rstrip('/')}/api/2.1/unity-catalog/model-services/{model_service}"
    resp = http_requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    config = resp.json().get("config", {})

    policies = [
        {
            "name": p.get("name"),
            "phases": (p.get("options") or {}).get("phases"),
            "action": (p.get("options") or {}).get("action", "block"),
        }
        for p in config.get("service_policies", [])
        if not p.get("is_deleted")
    ]

    destinations = config.get("routing", {}).get("destinations", [])
    routed_model = ""
    if destinations:
        routed_model = destinations[0].get("name", "").replace("system.ai.", "")

    # e.g. "tables/catalog.schema.name_payload" -> "catalog.schema.name_payload"
    table = (config.get("inference_table") or {}).get("table", "")
    inference_table = table.split("tables/", 1)[-1] if table else ""

    return {
        "policies": policies,
        "routed_model": routed_model,
        "inference_table": inference_table,
        "rate_limits": config.get("rate_limits"),
        "usage_tracking": config.get("usage_tracking"),
        "error": None,
    }


def print_gateway_summary(config: GatewayConfig, host: str, token: str) -> None:
    """Verify connectivity and display a model service's deployed configuration."""
    result = verify_gateway(host, token, config.model_service)
    deployed = fetch_service_config(host, token, config.model_service)

    print(f"{'=' * 70}")
    print(f"  Model Service ({config.provider}): {config.endpoint_name}")
    print(f"{'=' * 70}")

    status = "CONNECTED" if result["reachable"] else f"ERROR (HTTP {result['status']})"
    print(f"\n  Gateway Status:   {status}")
    if not result["reachable"]:
        print(f"    Error:          {result.get('error', '')}")
    print(f"  Gateway URL:      {host.rstrip('/')}/ai-gateway/mlflow/v1/chat/completions")
    print(f"  Model Service:    {config.model_service}")

    if deployed.get("error"):
        print(f"\n  Could not read deployed config: {deployed['error']}")
        print(f"\n{'=' * 70}")
        return

    print(f"  Routed Model:     {deployed['routed_model'] or 'unknown'}")

    print("\n  Guardrail Policies (deployed):")
    if deployed["policies"]:
        for p in deployed["policies"]:
            print(f"    {p['name']:<16} action={p['action']}  phases={p['phases']}")
    else:
        print("    (none configured)")

    print("\n  Inference Table:")
    print(f"    {deployed['inference_table'] or '(not configured)'}")

    # The table prefix is the service name, so a table can legitimately be
    # written to a different schema than the service lives in. Flag it, since
    # Acts 4/5 need to point Genie at the real location.
    table = deployed["inference_table"]
    if table:
        service_schema = ".".join(config.model_service.split(".")[:2])
        table_schema = ".".join(table.split(".")[:2])
        if service_schema != table_schema:
            print(f"    WARNING: table lives in '{table_schema}', not the service's")
            print(f"             own schema '{service_schema}'.")

    print("\n  Rate Limits:")
    if deployed["rate_limits"]:
        print(f"    {deployed['rate_limits']}")
    else:
        print("    (not configured — Act 6 burst tests will all return HTTP 200)")

    # This field is often absent even while usage IS being recorded, so don't
    # claim the system table is empty — point at how to check instead.
    print("\n  Usage Tracking:")
    if deployed["usage_tracking"]:
        print(f"    {deployed['usage_tracking']}")
    else:
        print("    (not reported in config; verify via system.ai_gateway.usage — Act 5)")

    print(f"\n{'=' * 70}")
