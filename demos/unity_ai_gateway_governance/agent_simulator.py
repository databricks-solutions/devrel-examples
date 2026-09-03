"""Simulate coding agents sending requests through Unity AI Gateway."""

import time
from dataclasses import dataclass

import mlflow
import requests

MAX_RETRIES = 5
INITIAL_BACKOFF = 2

# Status codes worth retrying: 429 (rate limited) and 5xx (transient server /
# guardrail-backend failures). A real guardrail block arrives as HTTP 200 with a
# denying service policy, so it never reaches this set and is never retried.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class SimulatedAgent:
    name: str
    display_name: str
    system_prompt: str
    model: str
    provider: str
    model_service: str


@dataclass
class GatewayClient:
    url: str
    token: str


def create_gateway_client(host: str, token: str) -> GatewayClient:
    """Create a client pointing at the Unity AI Gateway chat-completions URL.

    All governed model services share ONE gateway URL. The service is selected
    per request by the `model` field, which carries the fully-qualified Unity
    Catalog name (`catalog.schema.service`) — see `send_request`. Guardrails and
    rate limits are attached to each model service, so routing through this URL
    is what makes them apply.
    """
    url = f"{host.rstrip('/')}/ai-gateway/mlflow/v1/chat/completions"
    return GatewayClient(url=url, token=token)


def normalize_content(content) -> str:
    """Flatten provider-specific content shapes into a plain string.

    Gemini returns a list of blocks — [{"type": "text", "text": ...,
    "thoughtSignature": ...}] — while Claude and GPT return a string. Only the
    text is kept; `thoughtSignature` blobs are dropped.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def detect_policy_block(data: dict) -> dict | None:
    """Return the denying service policy, or None if the request wasn't blocked.

    Unity AI Gateway answers a guardrail block with HTTP **200**, not 400: the
    response carries `finish_reason: "content_filter"` and a top-level
    `databricks_service_policy` object naming the policy and why it fired.
    """
    policy = data.get("databricks_service_policy") or {}
    if policy.get("action") == "deny":
        return {
            "name": policy.get("name"),
            "action": policy.get("action"),
            "phase": policy.get("phase"),
            "reason": policy.get("reason"),
        }

    # Defensive: a filtered response without the policy object still counts.
    choices = data.get("choices") or [{}]
    if choices[0].get("finish_reason") == "content_filter":
        return {"name": "unknown", "action": "deny", "phase": None, "reason": None}
    return None


@mlflow.trace(span_type="CHAT_MODEL", name="gateway_request")
def send_request(
    client: GatewayClient,
    agent: SimulatedAgent,
    messages: list[dict],
) -> dict:
    """Send a chat completion through the gateway and return a result dict."""
    full_messages = [{"role": "system", "content": agent.system_prompt}] + messages

    mlflow.update_current_trace(
        tags={
            "agent": agent.name,
            "provider": agent.provider,
            "model_service": agent.model_service,
        }
    )

    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        try:
            # Timed per attempt, not per call, so retry backoff sleeps are not
            # billed as model latency.
            attempt_start = time.perf_counter()
            resp = requests.post(
                client.url,
                headers={"Authorization": f"Bearer {client.token}"},
                json={
                    "model": agent.model_service,
                    "messages": full_messages,
                    "max_tokens": 1024,
                },
                timeout=120,
            )
            latency_s = round(time.perf_counter() - attempt_start, 2)

            if resp.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code != 200:
                return {
                    "agent": agent.display_name,
                    "provider": agent.provider,
                    "model": agent.model,
                    "status": resp.status_code,
                    "content": None,
                    "tokens": None,
                    "policy": None,
                    "latency_s": latency_s,
                    "error": resp.text[:1000],
                }

            data = resp.json()
            usage = data.get("usage", {})
            return {
                "agent": agent.display_name,
                "provider": agent.provider,
                "model": agent.model,
                "status": 200,
                "content": normalize_content(data["choices"][0]["message"]["content"]),
                "tokens": {
                    "input": usage.get("prompt_tokens", 0),
                    "output": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0),
                },
                "policy": detect_policy_block(data),
                "latency_s": latency_s,
                "error": None,
            }
        except (requests.ConnectionError, requests.Timeout) as e:
            # A dropped connection or read timeout is transient in the same way a
            # 503 is, so retry it rather than reporting a spurious failure. Over a
            # long high-volume run these are likely enough to matter.
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            return {
                "agent": agent.display_name,
                "provider": agent.provider,
                "model": agent.model,
                "status": 504,
                "content": None,
                "tokens": None,
                "policy": None,
                "latency_s": None,
                "error": f"{type(e).__name__}: {e}",
            }
        except Exception as e:
            return {
                "agent": agent.display_name,
                "provider": agent.provider,
                "model": agent.model,
                "status": 500,
                "content": None,
                "tokens": None,
                "policy": None,
                "latency_s": None,
                "error": str(e),
            }


def run_scenario(
    client: GatewayClient,
    agent: SimulatedAgent,
    scenario: dict,
) -> dict:
    """Run a single scenario and return the result with scenario metadata."""
    result = send_request(client, agent, scenario["messages"])
    result["scenario"] = scenario["name"]
    result["description"] = scenario["description"]
    result["expected_outcome"] = scenario["expected_outcome"]
    result["guardrail_type"] = scenario["guardrail_type"]
    # The agent key (not the display name) so callers can group by agent or look
    # one up in the `agents` dict.
    result["agent_key"] = scenario["agent"]

    # A guardrail block arrives as HTTP 200 + a denying service policy, so the
    # status code alone is not enough to tell blocked from allowed.
    blocked = result["status"] != 200 or result["policy"] is not None
    actual = "blocked" if blocked else "allowed"
    result["actual_outcome"] = actual
    result["pass"] = actual == scenario["expected_outcome"]
    return result


def send_burst_request(
    client: GatewayClient,
    agent: SimulatedAgent,
    messages: list[dict],
) -> dict:
    """Send a single request, retrying only transient 5xx failures.

    Deliberately does NOT retry 429 — surfacing rate-limit rejections is the
    whole point of the burst test. But a transient guardrail-backend 5xx would
    otherwise show up as spurious 'error' rows, so those are retried briefly.
    """
    payload = {
        "model": agent.model_service,
        "messages": [{"role": "system", "content": agent.system_prompt}] + messages,
        "max_tokens": 256,
    }
    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                client.url,
                headers={"Authorization": f"Bearer {client.token}"},
                json=payload,
                timeout=120,
            )
        except Exception as e:
            return {"status": 500, "outcome": "error", "content": str(e), "total_tokens": 0}

        # Retry only transient server errors (not 429 — that's the signal we want).
        if resp.status_code in {500, 502, 503, 504} and attempt < MAX_RETRIES - 1:
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 200:
            data = resp.json()
            usage = data.get("usage", {})
            content = normalize_content(
                data.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            policy = detect_policy_block(data)
            return {
                "status": 200,
                "outcome": "blocked" if policy else "allowed",
                "content": content[:200],
                "total_tokens": usage.get("total_tokens", 0),
            }
        return {
            "status": resp.status_code,
            "outcome": "rate_limited" if resp.status_code == 429 else "error",
            "content": resp.text[:200],
            "total_tokens": 0,
        }


def run_burst_test(
    client: GatewayClient,
    agent: SimulatedAgent,
    scenario: dict,
    n_requests: int = 25,
) -> list[dict]:
    """Fire n_requests rapid sequential requests and return all results."""
    results = []
    for i in range(n_requests):
        result = send_burst_request(client, agent, scenario["messages"])
        result["request_num"] = i + 1
        results.append(result)
    return results


def print_burst_summary(results: list[dict]) -> None:
    """Print per-request outcomes then a pass/fail summary."""
    for r in results:
        icon = "+" if r["outcome"] == "allowed" else "x"
        line = f"  [{icon}] Request {r['request_num']:>2}  HTTP {r['status']}  {r['outcome']}"
        if r["outcome"] == "error":
            line += f"  — {r['content']}"
        print(line)
    print()
    allowed = sum(1 for r in results if r["outcome"] == "allowed")
    rate_limited = sum(1 for r in results if r["outcome"] == "rate_limited")
    errors = len(results) - allowed - rate_limited
    blocked = sum(1 for r in results if r["outcome"] == "blocked")
    errors -= blocked
    print(f"  Allowed:       {allowed}/{len(results)}")
    print(f"  Rate-limited:  {rate_limited}/{len(results)}")
    if blocked:
        print(f"  Guardrail-blocked: {blocked}/{len(results)}")
    if errors:
        print(f"  Errors:        {errors}/{len(results)}")


def print_result(result: dict) -> None:
    """Pretty-print a single scenario result."""
    passed = result["pass"]
    status_icon = "PASS" if passed else "FAIL"
    outcome_icon = "BLOCKED" if result["actual_outcome"] == "blocked" else "ALLOWED"

    # PASS/FAIL is the assertion verdict (actual == expected), not the gateway's
    # verdict — so a correctly blocked PII request is a PASS. Print the expected
    # outcome alongside it to keep those two axes from reading as contradictory.
    print(f"  [{status_icon}] {result['description']}")
    print(f"    Agent:    {result['agent']}")
    print(f"    Provider: {result.get('provider', '')}")
    print(f"    Model:    {result['model']}")
    print(f"    Expected: {result['expected_outcome'].upper()}")
    print(f"    Status:   {result['status']} ({outcome_icon})")

    # Guardrail blocks come back as HTTP 200, so the policy verdict — not the
    # status code — is what shows which guardrail fired and why.
    if result.get("policy"):
        p = result["policy"]
        phase = f", {p['phase']}" if p.get("phase") else ""
        print(f"    Policy:   {p['name']} (deny{phase})")
        if p.get("reason"):
            print(f"    Reason:   {p['reason']}")

    if result["actual_outcome"] == "allowed" and result["tokens"]:
        t = result["tokens"]
        print(f"    Tokens:   {t['total']} (in: {t['input']}, out: {t['output']})")

    # When a policy denied the request the only "content" is the block notice,
    # already reported above — don't dress it up as a model response.
    if result.get("content") and not result.get("policy"):
        print("-------------------------------- RESPONSE --------------------------------")
        preview = result["content"][:750]
        if len(result["content"]) > 750:
            preview += "..."
        print(f"    Response: {preview}")
        print("-------------------------------- RESPONSE --------------------------------")

    if result["error"]:
        error_preview = result["error"][:250]
        print(f"    Message:  {error_preview}")

    print()


def print_progress(result: dict, index: int, total: int) -> None:
    """Print one compact line for a result.

    `print_result` emits a dozen lines plus a response preview, which is right for
    a handful of scenarios but unreadable across a high-volume run. Use this for
    the running log and `print_result` for a few representative requests.
    """
    verdict = "ok  " if result["pass"] else "FAIL"
    tokens = (result.get("tokens") or {}).get("total") or 0
    latency = result.get("latency_s") or 0.0

    note = ""
    if result["status"] == 429:
        note = "  [rate-limited]"
    elif result["status"] != 200:
        note = f"  [HTTP {result['status']}]"
    elif result.get("policy"):
        note = f"  [{result['policy']['name']}]"

    print(
        f"  [{index:>3}/{total}] {verdict} {result['agent']:<12} {result['provider']:<7} "
        f"{result['actual_outcome']:<8} {tokens:>5} tok {latency:>6.1f}s  "
        f"{result['description'][:58]}{note}"
    )
