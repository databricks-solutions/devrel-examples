# Governing Coding Agent Sprawl with Unity AI Gateway

![AI Gateway Architecture](./images/ai_gateway_architecture.png)

**The problem:** your developers use Cursor, Claude Code, Codex CLI, Gemini CLI, and Pi, spread across different model providers. Each agent calls an LLM with its own API key. Nobody knows who is spending what, nothing stops a prompt carrying customer data, and there is no audit trail.

**The solution:** route every agent through Unity AI Gateway to a governed model service, one per provider. Each service is a Unity Catalog securable named `catalog.schema.service` that carries its own guardrails, inference table, and rate limits. Every request goes through one gateway, but policy is enforced per service.

| Pillar | What it does |
|--------|--------------|
| Security & auditability | Per-service guardrails (PII, jailbreak, unsafe content); requests logged to inference tables |
| Cost management | Per-service rate limits (QPM/TPM), unified billing, budgets per user or group |
| Observability | Inference tables in Delta, per-provider metrics, usage dashboard, MLflow tracing |

> **Reference:** [Governing Coding Agent Sprawl with Unity AI Gateway](https://www.databricks.com/blog/governing-coding-agent-sprawl-unity-ai-gateway)

## What the demo covers

| Act | What it shows |
|-----|---------------|
| 1. Verify the gateway | Reads each service's deployed config back from Unity Catalog: guardrail policies and their phases, routed model, inference table, rate limits. Fails fast and warns when anything is missing. |
| 2. Simulate the agent swarm | Five agents, each with its own persona prompt, each routed to its provider's service. 50 realistic coding requests. |
| 3. Guardrails in action | PII, jailbreak, and unsafe-content requests denied by each service's own policies. Unsafe content also shows defense in depth: what the gateway allows through, the model still refuses. |
| 4. The audit trail | Explore the three inference tables in plain English with Genie. No SQL. |
| 5. Usage tracking | Tokens and latency per provider, plus hourly aggregates from `system.ai_gateway.usage`. The chargeback view. |
| 6. Rate limiting | Two bursts against different providers prove budgets are per-service: 25 tiny requests trip QPM on Claude, 8 large ones trip TPM on OpenAI. Early requests pass, later ones get HTTP 429. |
| 7. MLflow tracing | Every request, allowed or denied, recorded as a trace. Browse by experiment or query the trace tables with Genie. |
| 8. Finale | A dashboard pulling it together: performance, cost, and per-agent usage. |

Agent-to-provider routing: Cursor and Claude Code use Claude, Codex CLI uses OpenAI, Gemini CLI and Pi use Gemini.

**About Act 2's volume.** Each agent sends 10 requests drawn from `clean_tasks.py` — linked lists, binary search, decorators, config and IaC, code review — issued round-robin so the provider rotates on every call. Sparse traffic makes the Genie questions in Acts 4 and 5 boring, which is the only reason the count matters. Budget 4–10 minutes. The catalog holds 15 tasks per agent, so raising `CLEAN_PER_AGENT` to 15 gets you 75 requests and nothing else changes.

Every trace is tagged with `agent`, `provider`, and `model_service`, which is what makes per-agent and per-provider attribution possible.

## Prerequisites

- A Databricks workspace with Unity Catalog
- A personal access token, for running from your host within cursor connecting to Databricks workspace
- Three Uniy AI Gateway model services, configured as below

## Configure the three model services

The notebook only consumes model services; it never creates or changes one. Create three, one per provider, and give them identical guardrail and rate-limit settings so the routed model is the only difference.

| Provider | Routed model | Agents |
|----------|--------------|--------|
| Claude | e.g. `databricks-claude-opus-4-8` | Cursor, Claude Code |
| OpenAI | e.g. `databricks-gpt-5-6-sol` | Codex CLI |
| Gemini | e.g. `databricks-gemini-3-6-flash` | Gemini CLI, Pi |

For each service:

1. **Create it.** Add an AI Gateway model service and pick the foundation model it routes to. It becomes a Unity Catalog securable named `catalog.schema.service`. That fully-qualified name is what the notebook sends as the request's `model` field.

![Create model service engpoint](./images/uaigw_images_1.png)

![Specify the catalog.schema.endpoint](./images/uaigw_images_2.png)

2. **Turn on guardrails.** Enable PII detection in **Block** mode (SSNs, credit cards, emails, phone numbers, names), jailbreak and prompt-injection detection, and unsafe-content detection. Where a phase is offered, enable both the request (`pre_call`) and the response (`post_call`) — Act 1 prints the phases you actually ended up with.

3. **Enable inference tables.** Point logging at a Unity Catalog schema. The table is named `<service-name>_payload`. Check the destination schema: the table can land in a different schema than the service itself, which makes the Genie setup for Acts 4 and 5 confusing. Act 1 discovers the real path and warns you when they diverge.

4. **Enable usage tracking.** Without it, `system.ai_gateway.usage` has no rows and Act 5's chargeback query comes back empty.

5. **Set rate limits.** Act 6 needs both a QPM and a TPM limit; without them every burst request returns 200 and the act shows nothing.

![enable_polcies_usage_limits](./images/uaigw_images_3.png)

   | Limit | Value | Why |
   |-------|-------|-----|
   | QPM | `8` | Well under the 25-request burst, so the ceiling is hit part-way through. The gateway allows some burst above the nominal limit, so leave room for a clean cutoff. |
   | TPM | `2000` | Low enough that the 8 large code-review requests exhaust it after one or two calls. |

   The two ceilings are enforced independently and whichever is hit first triggers the 429. Keep TPM high enough that the tiny QPM-test requests (~90 tokens each) are bound by the call limit rather than the token limit, and low enough that the large TPM-test requests are bound by tokens.

   > **These values suit Act 6 and will choke Act 2.** Limits are per-service, so one setting has to serve both. Act 2 sends 50 requests averaging ~1,100 tokens; against `QPM=8`/`TPM=2000` most draw a 429 and fall back on retry backoff. Either leave limits unset until you're ready to demo Act 6 (Acts 1–5 don't need them), or run the volume acts at roughly `QPM=60`/`TPM=100000` and drop down for Act 6. If Act 2 reports requests that "exhausted retries on HTTP 429", this is why.

Once all three exist, copy each fully-qualified name into the matching `*_MODEL_SERVICE` variable in `.env`, or into the notebook's config cell when running on Databricks.

 6.  **Act 7 : MLflow Tracing and Inspection**

All coding agent requests as traces are captured in the Unity Catalog table with schema `catalog.schema_name`, as set when
creating the MLflow experiment name.

Select `unityai-gateway-governance-demo` from the Experiments.

7. **Act 8: Fnale. Launch the Dashboard**.

![ai_gateway_dashboard](./images/uaigw_images_4.png)

![ai_gateway_dashboard](./images/uaigw_dashboard.png)


## How agents reach the gateway

All three services share one URL. The `model` field picks which one handles the request:

```bash
curl $DATABRICKS_HOST/ai-gateway/mlflow/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $DATABRICKS_TOKEN" \
  -d '{
    "model": "catalog.schema.service",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "What is Databricks?"}]
  }'
```

The API is OpenAI-compatible, so pointing a real coding agent at the gateway is a `base_url` change:

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DATABRICKS_TOKEN"],
    base_url=f"{DATABRICKS_HOST}/ai-gateway/mlflow/v1",
)
client.chat.completions.create(
    model="catalog.schema.service",   # selects the governed service
    messages=[{"role": "user", "content": "What is Databricks?"}],
    max_tokens=1024,
)
```

## Reading a guardrail block

A blocked request returns **HTTP 200**, not an error. The verdict is in the body:

```json
{
  "choices": [{
    "message": {"content": "This request was blocked by the 'PII' service policy."},
    "finish_reason": "content_filter"
  }],
  "databricks_service_policy": {
    "name": "PII",
    "action": "deny",
    "phase": "pre_call",
    "reason": "Content contains a social security number: 539-48-2817."
  }
}
```

So detect blocks with `databricks_service_policy.action == "deny"` (see `detect_policy_block` in `agent_simulator.py`). Filtering on `status_code != 200` will not find them.

Two things to know before building dashboards on this:

- **Denied requests never reach the inference table.** The table records model invocations, and a denied request never became one. It answers "what did our agents send, and what did it cost?" — not "what did we block?" The blocking evidence lives in the policy verdicts and MLflow traces.
- **Response shape varies by provider.** Gemini returns `content` as a list of blocks (`[{"type": "text", "text": ..., "thoughtSignature": ...}]`) where Claude and GPT return a string. `normalize_content` in `agent_simulator.py` flattens both and drops the `thoughtSignature` blobs.

A related trap when writing your own clean prompts: because PII runs on `post_call` too, a harmless prompt can be denied for what the *model* wrote back. A request for a `pyproject.toml` gets denied when the model fills in an author email, and an nginx config gets denied for the upstream IP address. Ask for the artifact without those fields.

## Set up Genie for Acts 4 and 5

1. Open **Genie** in your workspace and create an agent.
2. Add all three `<service-name>_payload` tables as data sources. Act 1 prints the exact paths under `Discovered inference tables:` — use those rather than guessing, since a table may live outside its service's schema. Add `system.ai_gateway.usage` too, for Act 5.
3. Keep the space open during the demo. Acts 4 and 5 supply questions to paste in; no code to run.

## Running locally

1. Create a `.env` from the template:

    ```bash
    cd unity_ai_gateway_governance
    cp env-template .env
    ```

    | Variable | Description |
    |----------|-------------|
    | `DATABRICKS_HOST` | Workspace URL, e.g. `https://<workspace>.cloud.databricks.com` |
    | `DATABRICKS_TOKEN` | Personal access token |
    | `CLAUDE_MODEL_SERVICE` | Fully-qualified name of the Claude service; sent as the `model` field |
    | `CLAUDE_MODEL` | Model it routes to, e.g. `databricks-claude-opus-4-8`. Display label only |
    | `OPENAI_MODEL_SERVICE` | Fully-qualified name of the OpenAI service |
    | `OPENAI_MODEL` | Model it routes to, e.g. `databricks-gpt-5-6-sol`. Display label only |
    | `GEMINI_MODEL_SERVICE` | Fully-qualified name of the Gemini service |
    | `GEMINI_MODEL` | Model it routes to, e.g. `databricks-gemini-3-6-flash`. Display label only |
    | `UC_CATALOG` | Catalog holding the inference tables; each service's table is discovered at runtime |
    | `MLFLOW_SCHEMA` | Schema holding the MLflow trace tables |

2. Install and launch:

    ```bash
    uv sync
    jupyter notebook ai_gateway_demo.ipynb
    ```

    Or run the `ai_gateway_demo.ipynb` from wihtin your Cursor IDE.

3. Run Acts 1–3 and Act 6 interactively. These call the model services directly.

   > Acts 4 and 5 need a Databricks workspace, since they drive Genie against the inference tables. Deploy the notebook (below) and keep the Genie space open beside it. Act 6 also needs QPM/TPM limits configured.

## Deploying to Databricks

The project uses [Declarative Automation Bundles](https://docs.databricks.com/en/dev-tools/bundles/index.html) to push the notebook and its modules to a workspace.

1. Install the CLI:

    ```bash
    brew install databricks/tap/databricks
    ```

2. Authenticate:

    ```bash
    databricks auth login --host https://<your-workspace>.cloud.databricks.com
    ```

3. Validate and deploy:

    ```bash
    cd unity_ai_gateway_governance
    databricks bundle validate
    databricks bundle deploy
    ```

4. Open `ai_gateway_demo` in the workspace and run the acts. The notebook detects the Databricks runtime and pulls host and token from `dbutils`, so no `.env` is needed.

> **Tip:** edit `databricks.yml` to change the target workspace or add targets such as staging and production.

## File structure

```
unity_ai_gateway_governance/
├── databricks.yml          # Declarative Automation Bundle configuration
├── ai_gateway_demo.ipynb   # Demo notebook (runs locally and on Databricks)
├── gateway_config.py       # GatewayConfig + per-service verification and config lookup
├── agent_simulator.py      # SimulatedAgent, GatewayClient, policy-block detection, retries
├── scenarios.py            # Guardrail payloads (PII, injection, unsafe) + clean-scenario builder
├── clean_tasks.py          # 15 coding tasks per agent (10 used by default)
├── prompts.py              # System prompt per agent persona
├── observability.py        # SQL query templates for the inference tables
├── images/
│   └── ai_gateway_architecture.png
├── env-template            # Environment variable template (local runs)
└── README.md
```
