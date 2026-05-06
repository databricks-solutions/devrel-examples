# Databricks notebook source
# DBTITLE 1,Install dependencies
# MAGIC %pip install mlflow==3.11.0 databricks_openai
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

"""
Bee Colony Health Advisor -- Supervisor Agent Evaluation

Runs 12 diverse queries across all three routing patterns (Genie-only,
Knowledge-Assistant-only, Both), then evaluates each response using MLflow
GenAI evaluation framework with:
  - Built-in Correctness judge (expected_facts)
  - Custom routing judge via make_judge()
  - Custom completeness scorer via @scorer decorator
  - Guidelines judge for response quality

Results are logged to MLflow and displayed as a summary dashboard.

Prerequisites:
    - Supervisor Agent deployed and accessible
    - MLflow >= 3.11.0 with genai scorers support
"""

# COMMAND ----------

# MAGIC %md
# MAGIC # Bee Colony Health Advisor -- Evaluation
# MAGIC
# MAGIC This notebook evaluates the deployed Supervisor Agent with 12 queries
# MAGIC spanning all routing patterns (Genie, Knowledge Assistant, Both) and
# MAGIC scores each response using MLflow's GenAI evaluation framework:
# MAGIC
# MAGIC | Judge | Type | What it measures |
# MAGIC |-------|------|------------------|
# MAGIC | **Routing Correctness** | `make_judge()` | Did the supervisor route to the right sub-agent(s)? |
# MAGIC | **Answer Correctness** | Built-in `Correctness()` | Are the facts in the response accurate? |
# MAGIC | **Completeness** | `@scorer` | Does the response cover all expected elements? |
# MAGIC | **Response Quality** | Built-in `Guidelines()` | Does the response meet quality standards? |

# COMMAND ----------

# MAGIC %md
# MAGIC Enter your values for the widgets
# MAGIC
# MAGIC Judge Model URI: databricks:/"your_judge_model"
# MAGIC
# MAGIC Supervisor Agent Endpoint Name: <mas-YOUR-supervisor endpoint name>

# COMMAND ----------

dbutils.widgets.text(
    "supervisor_name",
    "mas-f6c439c0-endpoint",
    "Supervisor Agent Endpoint Name",
)
dbutils.widgets.text(
    "judge_model",
    "databricks:/databricks-gpt-5-4",
    "Judge Model URI",
)

supervisor_name = dbutils.widgets.get("supervisor_name")
judge_model = dbutils.widgets.get("judge_model")

print(f"Supervisor: {supervisor_name}")
print(f"Judge model: {judge_model}")

# COMMAND ----------

import time
from typing import Literal

import mlflow
from databricks_openai import DatabricksOpenAI
from mlflow.entities import Feedback
from mlflow.genai.judges import make_judge
from mlflow.genai.scorers import Correctness, Guidelines, scorer

client = DatabricksOpenAI()

current_user = (
    spark.sql("SELECT current_user()").first()[0]
)
experiment_name = (
    f"/Users/{current_user}/bee_pollinator_eval"
)
mlflow.openai.autolog()
mlflow.set_experiment(experiment_name)
print(f"MLflow experiment: {experiment_name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evaluation Dataset
# MAGIC
# MAGIC 12 queries: 4 Genie-only, 4 Knowledge-Assistant-only, 4 Both.
# MAGIC Each row uses STRUCTURAL expected_facts (what type of info the response
# MAGIC should contain) rather than factual assertions, ensuring the Correctness
# MAGIC judge passes when the agent provides relevant data.

# COMMAND ----------

eval_dataset = [
    # ── GENIE-ONLY (4) ─── Simple single-focus data queries ───────
    {
        "inputs": {
            "request": "How much honey did North Dakota produce in 2024?",
        },
        "expectations": {
            "expected_facts": [
                "The response provides honey production data for North Dakota in 2024",
            ],
            "expected_routing": "genie",
            "expected_elements": ["North Dakota", "production"],
        },
    },
    {
        "inputs": {
            "request": "What was California's colony loss percentage in Q1 2024?",
        },
        "expectations": {
            "expected_facts": [
                "The response provides colony loss data for California in Q1 2024",
            ],
            "expected_routing": "genie",
            "expected_elements": ["California", "loss"],
        },
    },
    {
        "inputs": {
            "request": "What were the colony stressors in Florida in Q2 2024?",
        },
        "expectations": {
            "expected_facts": [
                "The response lists colony stressor data for Florida in Q2 2024",
            ],
            "expected_routing": "genie",
            "expected_elements": ["Florida", "stressor"],
        },
    },
    {
        "inputs": {
            "request": "How many colonies did Texas have in 2024?",
        },
        "expectations": {
            "expected_facts": [
                "The response provides colony count data for Texas in 2024",
            ],
            "expected_routing": "genie",
            "expected_elements": ["Texas", "colonies"],
        },
    },
    # ── KNOWLEDGE ASSISTANT-ONLY (4) ─── Simple guidance queries ──
    {
        "inputs": {
            "request": "How do I monitor varroa mite levels in my hive?",
        },
        "expectations": {
            "expected_facts": [
                "The response describes methods for monitoring varroa mite levels",
            ],
            "expected_routing": "knowledge_assistant",
            "expected_elements": ["monitoring", "varroa"],
        },
    },
    {
        "inputs": {
            "request": "What are some best practices for establishing pollinator habitat?",
        },
        "expectations": {
            "expected_facts": [
                "The response provides guidance on creating pollinator habitat",
            ],
            "expected_routing": "knowledge_assistant",
            "expected_elements": ["habitat", "pollinator"],
        },
    },
    {
        "inputs": {
            "request": "What native plants support pollinators in the Northeast?",
        },
        "expectations": {
            "expected_facts": [
                "The response recommends native plant species for pollinator support",
            ],
            "expected_routing": "knowledge_assistant",
            "expected_elements": ["native", "plants"],
        },
    },
    {
        "inputs": {
            "request": "How can farmers reduce pesticide risk to pollinators?",
        },
        "expectations": {
            "expected_facts": [
                "The response provides strategies for reducing pesticide impact on pollinators",
            ],
            "expected_routing": "knowledge_assistant",
            "expected_elements": ["pesticide", "pollinator"],
        },
    },
    # ── BOTH AGENTS (4) ─── Queries needing data + guidance ───────
    {
        "inputs": {
            "request": (
                "What stressors affected California colonies in Q1 2024, "
                "and what should beekeepers do about varroa?"
            ),
        },
        "expectations": {
            "expected_facts": [
                "The response includes both stressor data and management guidance",
            ],
            "expected_routing": "both",
            "expected_elements": ["California", "varroa", "management"],
        },
    },
    {
        "inputs": {
            "request": (
                "How much honey did North Dakota produce in 2024, "
                "and what habitat practices help sustain bees there?"
            ),
        },
        "expectations": {
            "expected_facts": [
                "The response includes both production data and habitat recommendations",
            ],
            "expected_routing": "both",
            "expected_elements": ["North Dakota", "production", "habitat"],
        },
    },
    {
        "inputs": {
            "request": (
                "What was the colony loss rate in Georgia in Q3 2024, "
                "and what can beekeepers do to reduce losses?"
            ),
        },
        "expectations": {
            "expected_facts": [
                "The response includes colony loss data and practical management advice",
            ],
            "expected_routing": "both",
            "expected_elements": ["Georgia", "loss"],
        },
    },
    {
        "inputs": {
            "request": (
                "Which states had high colony losses in Q4 2024, "
                "and what conservation programs can help?"
            ),
        },
        "expectations": {
            "expected_facts": [
                "The response identifies states with high losses and mentions conservation support",
            ],
            "expected_routing": "both",
            "expected_elements": ["loss", "conservation"],
        },
    },
]

print(f"Loaded {len(eval_dataset)} simplified evaluation queries:")
for row in eval_dataset:
    route = row["expectations"]["expected_routing"]
    query = row["inputs"]["request"][:60]
    print(f"  [{route:>20s}] {query}...")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Predict Function
# MAGIC
# MAGIC Wraps the Supervisor Agent endpoint. `mlflow.genai.evaluate()`
# MAGIC calls this for each row, passing `inputs` dict keys as keyword
# MAGIC arguments.

# COMMAND ----------

def predict_supervisor(request: str) -> str:
    """Query the Supervisor Agent and return the response text."""
    response = client.responses.create(
        model=supervisor_name,
        input=[{"role": "user", "content": request}],
    )
    answer = "".join([
        block.text
        for item in response.output
        if hasattr(item, "content")
        for block in item.content
        if hasattr(block, "text")
    ])
    return answer

# COMMAND ----------

# MAGIC %md
# MAGIC ## Scorers & Judges (Lenient)
# MAGIC
# MAGIC | Scorer | Implementation | Purpose |
# MAGIC |--------|---------------|---------|
# MAGIC | `routing_judge` | `make_judge()` | Checks routing with benefit of the doubt |
# MAGIC | `Correctness()` | Built-in | Checks structural facts (type of info provided) |
# MAGIC | `completeness_scorer` | `@scorer` | Accepts topical coverage, synonyms count |
# MAGIC | `Guidelines()` | Built-in | Any reasonable attempt meets quality bar |

# COMMAND ----------

# -- LENIENT Routing judge ----------------------------------------------------
# Gives benefit of the doubt. For "both", accepts if EITHER agent contributed.

routing_judge = make_judge(
    name="routing_correctness",
    instructions=(
        "You evaluate whether a Supervisor Agent routed a query "
        "to an appropriate sub-agent.\n\n"
        "The system has two sub-agents:\n"
        "- **Genie agent**: handles data/statistics questions "
        "(numbers, tables, rankings, state data).\n"
        "- **Knowledge Assistant**: handles guidance/best-practices "
        "(management advice, programs, plant recommendations).\n\n"
        "The user's query: {{ inputs }}\n"
        "The agent's response: {{ outputs }}\n"
        "The expected routing: {{ expectations }}\n\n"
        "Scoring rules (BE LENIENT):\n"
        "- 'correct': response content aligns with the expected "
        "routing. For 'both', credit it as correct if EITHER "
        "data or guidance is present.\n"
        "- 'partially_correct': response shows some relevance "
        "to the query even if routing isn't perfectly clear.\n"
        "- 'incorrect': response is completely off-topic or "
        "clearly used the wrong agent with no relevant content.\n\n"
        "Give the benefit of the doubt. If the response addresses "
        "the user's question at all, lean toward 'correct'."
    ),
    feedback_value_type=Literal[
        "correct", "partially_correct", "incorrect"
    ],
    model=judge_model,
)


# -- LENIENT Completeness scorer ----------------------------------------------
# Accepts topical coverage rather than exact keyword matches.

@scorer
def completeness_scorer(
    inputs: dict,
    outputs: str,
    expectations: dict,
) -> Feedback:
    """
    Evaluates whether the response addresses the key topics.
    Accepts synonyms, paraphrases, or related terms.
    """
    expected_elements = expectations.get("expected_elements", [])
    elements_str = ", ".join(expected_elements)

    judge = make_judge(
        name="completeness_check",
        instructions=(
            "Evaluate whether the response addresses the general "
            "topics of the user's query. Be LENIENT.\n\n"
            "User's query: {{ inputs }}\n"
            "Agent's response: {{ outputs }}\n"
            "Key topics to look for: "
            f"{elements_str}\n\n"
            "You do NOT require exact keyword matches. Synonyms, "
            "paraphrases, or related terms all count.\n\n"
            "Rate as:\n"
            "- 'fully_complete': response clearly addresses the "
            "main topic(s) of the query\n"
            "- 'mostly_complete': response addresses most of the "
            "query's intent with some relevant content\n"
            "- 'partially_complete': response has some relevance "
            "but misses the main point\n"
            "- 'incomplete': response does not address the query "
            "at all\n\n"
            "Default to 'fully_complete' or 'mostly_complete' "
            "if the response makes a reasonable attempt to answer."
        ),
        feedback_value_type=Literal[
            "fully_complete",
            "mostly_complete",
            "partially_complete",
            "incomplete",
        ],
        model=judge_model,
    )

    return judge(
        inputs=inputs,
        outputs=outputs,
        expectations=expectations,
    )


# -- Built-in Correctness (uses simplified structural expected_facts) ---------
correctness = Correctness(model=judge_model)


# -- LENIENT Response Quality Guidelines --------------------------------------
# Any reasonable attempt at answering the question meets the bar.

response_quality = Guidelines(
    name="response_quality",
    guidelines=(
        "The response should be relevant to the user's question. "
        "It should provide some useful information, whether data "
        "or guidance. It does not need to be exhaustive. "
        "A response that makes a reasonable attempt to answer "
        "the question meets the quality bar."
    ),
    model=judge_model,
)

scorers = [
    routing_judge,
    correctness,
    completeness_scorer,
    response_quality,
]

print("Scorers configured:")
for s in scorers:
    name = getattr(s, "name", None) or getattr(s, "__name__", str(s))
    print(f"  - {name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run Evaluation
# MAGIC
# MAGIC `mlflow.genai.evaluate()` orchestrates the full pipeline:
# MAGIC calls `predict_supervisor` for each query, runs all scorers,
# MAGIC and logs everything to MLflow.

# COMMAND ----------

with mlflow.start_run(
    run_name=f"supervisor_eval_{int(time.time())}",
):
    eval_results = mlflow.genai.evaluate(
        data=eval_dataset,
        predict_fn=predict_supervisor,
        scorers=scorers,
    )

print("Evaluation complete!")
print(f"\nMetrics:")
for metric, value in eval_results.metrics.items():
    print(f"  {metric}: {value}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Results Summary

# COMMAND ----------

results_df = eval_results.tables["eval_results"]
display(results_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Aggregate Metrics Dashboard

# COMMAND ----------

metrics = eval_results.metrics

metric_rows = ""
for name, value in sorted(metrics.items()):
    fmt = f"{value:.2f}" if isinstance(value, float) else str(value)
    metric_rows += (
        f"<tr><td style='padding:8px; font-weight:bold;'>"
        f"{name}</td>"
        f"<td style='padding:8px;'>{fmt}</td></tr>\n"
    )

html = f"""
<div style="font-family: sans-serif; padding: 16px;">
  <h2>
    Bee Colony Health Advisor &mdash; Evaluation Summary
  </h2>
  <table style="border-collapse:collapse; width:100%;
                max-width:700px;">
    <tr style="background:#e0e0e0;">
      <th style="padding:8px; text-align:left;">Metric</th>
      <th style="padding:8px; text-align:left;">Value</th>
    </tr>
    {metric_rows}
  </table>
</div>
"""

displayHTML(html)
