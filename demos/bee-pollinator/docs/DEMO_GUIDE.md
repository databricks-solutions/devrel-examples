# Conference Booth Demo Guide — Bee Pollinator Supervisor Agent

**Target Demo Time:** 5 minutes
**Audience:** Data practitioners, ML engineers, application developers

This guide provides the exact flow for demonstrating the Bee Colony Health Supervisor Agent at conference booths.

---

## Demo Overview

**Key Message:** "Supervisor Agents automatically route questions between structured data and unstructured documents, so users get comprehensive answers without knowing which system to query."

**Demo Structure:**
1. [0-1 min] Introduction & architecture
2. [1-2 min] Data query → Genie routing
3. [2-3 min] Document query → Knowledge Assistant routing
4. [3-4 min] Cross-modal query → Combined routing (the "wow" moment)
5. [4-5 min] Show MLflow traces & evaluations

---

## Before the Demo

### Preparation Checklist
- [ ] Open Supervisor Agent in Databricks workspace
- [ ] Clear conversation history (click Reset)
- [ ] Have test queries ready to copy-paste (see below)
- [ ] Bookmark MLflow experiment URL
- [ ] Test WiFi latency (run a practice query)
- [ ] Have this guide open on second screen/tablet

### Key URLs to Bookmark
```
Supervisor Agent: https://<workspace>/ml/agents/<supervisor-agent-name>
MLflow Experiment: https://<workspace>/ml/experiments/<experiment-id>
Traces: https://<workspace>/ml/experiments/<experiment-id>/traces
```

---

## 5-Minute Demo Script

### [0-1 min] Introduction

**Opening:**
> "I'm going to show you a Supervisor Agent that answers questions about bee colony health by automatically routing between two data sources: USDA production and loss data in Delta tables, and beekeeping guidance documents in PDFs."

**Show the architecture** (if you have a slide/diagram):
```
       User Question
            |
            v
    ┌───────────────┐
    │  Supervisor   │
    │    Agent      │
    └───┬───────┬───┘
        │       │
        v       v
    ┌─────┐ ┌─────────┐
    │Genie│ │Knowledge│
    │Space│ │Assistant│
    └─────┘ └─────────┘
```

**Key talking point:**
> "Most enterprise data lives in two worlds: structured tables and unstructured documents. Supervisor Agents eliminate the need for users to know which system to query."

---

### [1-2 min] Demo Query #1: Data Query → Genie

**Copy-paste this query:**
```
Which 5 states had the highest colony loss rates in 2023?
```

**While it processes (~10-15 seconds):**
> "This is a pure data question, so the Supervisor should route it to the Genie Space, which queries our Delta tables with SQL."

**When response appears:**
- Point out: "See, it queried the colony_loss table and returned states ranked by loss percentage."
- Highlight if visible: "The Supervisor decided this needed Genie, not the document assistant."
- Show the data table (e.g., California 35%, Montana 32%, etc.)

**Talking point:**
> "Genie Spaces let you ask natural language questions over structured data. The Supervisor knew this was a statistics question and routed it there automatically."

---

### [2-3 min] Demo Query #2: Document Query → Knowledge Assistant

**Click Reset** to clear conversation (optional but recommended for clarity)

**Copy-paste this query:**
```
What does the Varroa Management Guide recommend for monitoring mite levels?
```

**While it processes (~15-20 seconds):**
> "This is a guidance question, not a data question. The Supervisor should route it to the Knowledge Assistant, which searches our 4 beekeeping PDFs."

**When response appears:**
- Point out: "It cited specific methods from the Varroa Management Guide — alcohol wash, sugar roll, treatment thresholds."
- Highlight if visible: "Notice it's pulling from documents, not querying tables."
- Show document citations if available (e.g., "According to the Varroa Management Guide, page 12...")

**Talking point:**
> "Knowledge Assistants search PDFs, text files, or any documents in Unity Catalog. The Supervisor recognized this was a best-practices question and routed it to the right tool."

---

### [3-4 min] Demo Query #3: Cross-Modal → BOTH Agents ⭐

**Click Reset** (optional)

**Copy-paste this query:**
```
California lost 35% of colonies in 2023. What varroa management practices should California beekeepers prioritize?
```

**While it processes (~20-30 seconds):**
> "This is where it gets interesting. This question needs BOTH data insight and expert guidance. Watch what the Supervisor does."

**When response appears:**
- Point out the two-part answer:
  1. **Data confirmation:** "Yes, California had 35% colony loss, with varroa identified as a top stressor" (from Genie)
  2. **Actionable guidance:** "Here are varroa treatment protocols for CA climate..." (from Knowledge Assistant)
- Highlight: "The Supervisor queried both agents and synthesized a comprehensive answer."

**Talking point:**
> "This is the power of the Supervisor pattern. Users don't need to know they're querying two different systems. They just ask, and the Supervisor orchestrates the response."

**Bonus (if time):**
> "In production, you'd have dozens of agents — sales data, inventory systems, policy docs, HR knowledge bases — and the Supervisor would route to the right combination based on the question."

---

### [4-5 min] Show MLflow Traces & Evaluations

**Navigate to MLflow** (click "View in MLflow" link if available, or use bookmarked URL)

**Step 1: Show the Traces Tab (~30 seconds)**
1. Click **"Traces"** tab in the MLflow experiment
2. Show the most recent traces (your 3 demo queries should be visible)
3. Click on the last trace (the cross-modal query)

**What to highlight:**
- "Every query is automatically logged to MLflow"
- "You can see inputs, outputs, execution time"
- Point out the **spans** (sub-agent calls): "Here you can see it called Genie first, then Knowledge Assistant, then synthesized"

**Talking point:**
> "Observability is built-in. You get full tracing for debugging and monitoring, including which sub-agents were called and how long each step took."

**Step 2: Show Evaluation (if you have time, ~1 minute)**

Option A: **Pre-computed eval** (do this before the booth opens)
- Show evaluation results tab in MLflow
- "We ran automated evaluations on 50 test questions"
- Show metrics: "Answer relevance: 87%, Faithfulness: 92%"
- Point out: "You can track quality over time as you iterate"

Option B: **Live eval** (only if you have 2 minutes and good WiFi)
```python
# Run this in a notebook before the demo
import mlflow
import pandas as pd

eval_data = pd.DataFrame({
    "input": [
        "How do bees help crops?",
        "What's the decline rate of pollinators?",
        "Which crops depend on bees?"
    ]
})

results = mlflow.genai.evaluate(
    data=eval_data,
    model="Bee-Colony-Health-Advisor",  # Your supervisor endpoint
    scorers=[mlflow.genai.scorers.answer_relevance()],
    experiment=experiment_id,
    run_name="booth-demo-eval"
)

print(f"Relevance: {results.metrics['answer_relevance/mean']:.1%}")
```

**Talking point:**
> "MLflow has built-in evaluation for GenAI apps. You can test against a suite of questions and track metrics like relevance, correctness, and faithfulness."

---

## Backup Queries (If Needed)

If any queries fail or you need variety:

**Alternative Data Query:**
```
Show me honey production trends in California over the last 5 years.
```

**Alternative Document Query:**
```
Which native plants should I recommend for spring forage in the Northeast?
```

**Alternative Cross-Modal Query:**
```
North Dakota produces the most honey but has significant colony loss. What varroa management practices should beekeepers there prioritize?
```

---

## Common Audience Questions

### Q: "How does the Supervisor know which agent to route to?"
**A:** "The Supervisor uses LLM-based routing. You give it instructions (which we saw when we created it) that describe when to use each agent. For simple rules, you can even use function calling or structured outputs, but the LLM approach handles ambiguous cases well."

### Q: "Can I use my own data?"
**A:** "Absolutely. The data we're using is public USDA data, but you'd connect your own Delta tables (for Genie), your own PDFs or docs (for Knowledge Assistant), and even your own custom agents. The Supervisor pattern is data-agnostic."

### Q: "How much does this cost?"
**A:** "Pricing depends on the model you choose and usage. For development, you can use smaller models. For production, you pay for model inference and compute. The good news is you only pay for what you use — no infrastructure to manage."

### Q: "What if the Supervisor routes to the wrong agent?"
**A:** "Great question. That's where observability comes in. You can see in MLflow which agent was called, and you can refine the Supervisor's instructions based on those traces. You can also add evals to catch routing errors automatically."

### Q: "Can the Supervisor call more than 2 agents?"
**A:** "Yes! You can add as many agents as you want. In production, you might have a dozen specialized agents — one for sales data, one for inventory, one for HR policies, one for customer support history, etc. The Supervisor routes to any combination based on the question."

### Q: "Does this work with non-Databricks agents?"
**A:** "The Supervisor Agent framework is Databricks-native, but you can integrate external APIs or custom agents by wrapping them in Unity Catalog functions. So yes, you can orchestrate both Databricks agents and your own custom tools."

### Q: "How long did this take to set up?"
**A:** "About 30 minutes. The data ingestion took 10 minutes, document upload took 5, and creating the 3 agents (Genie, Knowledge Assistant, Supervisor) took about 15 minutes total. We have a full setup guide in the repo."

### Q: "Can I try this myself?"
**A:** "Yes! The full code and setup guide are in our GitHub repo: [provide link]. It's all public USDA data, so you can deploy it in your own Databricks workspace and experiment."

---

## Troubleshooting During Demo

### Issue: Query takes a long time (>30 seconds)
**What to say:**
> "The Supervisor is querying multiple systems here, so it can take a moment. In production, you'd optimize this with caching, smaller models, or parallel agent calls."

**What to do:**
- Let it finish (don't refresh!)
- If it times out, apologize and use a backup query
- Blame conference WiFi if needed 😄

### Issue: Wrong routing (e.g., data query goes to KA)
**What to say:**
> "Interesting — it routed to the document assistant instead of the data tables. This is where iterative refinement comes in. You'd look at the trace in MLflow, adjust the Supervisor instructions, and redeploy."

**What to do:**
- Show the trace in MLflow (turn it into a teachable moment)
- Emphasize observability and iteration
- Use a backup query that you know works

### Issue: Response is wrong or low-quality
**What to say:**
> "The response isn't quite what we'd want in production. This is where evaluation comes in — you'd add this to your test set, score it, and iterate on the agent configuration or the underlying data."

**What to do:**
- Don't dwell on it — acknowledge and move on
- Pivot to showing MLflow traces/evals
- Emphasize iteration and testing

---

## Key Takeaways to Emphasize

1. **Automatic routing eliminates cognitive load**
   - Users don't need to know which system to query
   - One interface for all enterprise knowledge

2. **Composability is the key**
   - Mix structured data (Genie), documents (KA), and custom tools
   - Add more agents as your use case grows

3. **Observability is built-in**
   - Every query is traced in MLflow
   - Debug, monitor, and improve over time

4. **Pattern is generalizable**
   - Not just for bees 🐝 — works for customer support, finance, healthcare, etc.
   - Any domain with mixed data types benefits

5. **Quick to deploy, easy to iterate**
   - 30-minute setup with public data
   - Refine instructions and retrain based on real usage

---

## Post-Demo: Next Steps for Interested Visitors

**If they want to learn more:**
1. Share the GitHub repo URL
2. Point them to Databricks Agent Framework docs: https://docs.databricks.com/en/generative-ai/agent-bricks/
3. Recommend they try the FEMA Supervisor demo (more dramatic use case)
4. Offer to connect them with a Databricks SA

**If they want to build their own:**
1. Sign up for Databricks workspace (free trial available)
2. Follow `BOOTH_SETUP.md` in the repo
3. Start with their own use case (customer support, finance, etc.)
4. Join the Databricks Community forums for help

---

## Demo Logistics

### Setup Before Booth Opens
- [ ] Deploy the demo (30 min, see `BOOTH_SETUP.md`)
- [ ] Test all 3 queries
- [ ] Bookmark MLflow URLs
- [ ] Print this guide or load on tablet
- [ ] Charge laptop, bring charger + dongle
- [ ] Test on conference WiFi if possible

### During the Demo
- Keep demos short (5 min max) — let people ask questions
- Don't get stuck debugging — move to backup queries
- Smile and engage — the tech sells itself
- Collect emails/cards from interested visitors

### After the Demo
- Clear conversation history for next visitor
- If a query failed, make a note to debug later
- Recharge between demos (physically and mentally 😄)

---

## Sample Talking Track (Full 5-Minute Flow)

> "Hey, thanks for stopping by! I'm going to show you a Supervisor Agent in 5 minutes. It's like a smart router for your data."
>
> [Show architecture]
> "Most companies have data in two places: structured tables and unstructured documents. Users waste time figuring out which system to query. Supervisor Agents fix this."
>
> [Query 1]
> "Let me ask a data question: 'Which states had highest colony loss?' Watch — it routes to our SQL tables automatically and returns ranked results."
>
> [Query 2]
> "Now a document question: 'What does the Varroa Guide recommend?' It routes to our Knowledge Assistant and cites the PDF."
>
> [Query 3]
> "Here's the magic: 'California lost 35% of colonies. What should they do?' It queries BOTH — gets the data, gets the guidance, and synthesizes a complete answer."
>
> [MLflow]
> "And it's all traced in MLflow. You can see which agents were called, how long each took, and run evaluations to track quality over time."
>
> [Wrap up]
> "This pattern works for any domain — customer support, finance, healthcare. If you have data in multiple systems, Supervisor Agents make it seamless. Here's the repo if you want to try it yourself!"

---

## MLflow Integration Details

### Finding Experiment and Trace IDs

**Via UI:**
1. Machine Learning > Experiments
2. Find your Supervisor Agent experiment (usually matches agent name)
3. Click info icon (ⓘ) in upper left for experiment ID

**Programmatically:**
```python
from databricks.sdk import WorkspaceClient
import mlflow

w = WorkspaceClient()

# Get supervisor endpoint name
supervisor_name = "Bee-Colony-Health-Advisor"

# Get experiment
experiment = mlflow.get_experiment_by_name(supervisor_name)
experiment_id = experiment.experiment_id

print(f"Experiment: {experiment_id}")

# Get recent traces
traces = mlflow.search_traces(
    experiment_ids=[experiment_id],
    max_results=10,
    order_by=["timestamp DESC"]
)

print(f"Found {len(traces)} recent traces")

# Get latest trace URL
workspace_url = "https://your-workspace.cloud.databricks.com"
latest_trace_id = traces.iloc[0]["request_id"]
trace_url = f"{workspace_url}/ml/experiments/{experiment_id}/traces/{latest_trace_id}"

print(f"Latest trace: {trace_url}")
```

### Running Evaluations (Pre-Booth)

**Do this before booth opens to have results ready:**

```python
import mlflow
import pandas as pd

# Evaluation dataset
eval_data = pd.DataFrame({
    "input": [
        "Which states had highest colony loss in 2023?",
        "What varroa treatments does the guide recommend?",
        "California lost 35% of colonies. What should they prioritize?",
        "Show honey production trends in Florida",
        "Which native plants support spring pollinators?",
    ]
})

# Run evaluation
results = mlflow.genai.evaluate(
    data=eval_data,
    model="Bee-Colony-Health-Advisor",  # Your supervisor endpoint
    scorers=[
        mlflow.genai.scorers.answer_relevance(),
        mlflow.genai.scorers.faithfulness(),
    ],
    experiment=experiment_id,
    run_name="booth-demo-eval"
)

# View results
print(f"Relevance: {results.metrics['answer_relevance/mean']:.1%}")
print(f"Faithfulness: {results.metrics['faithfulness/mean']:.1%}")

# Show URL
eval_url = f"{workspace_url}/ml/experiments/{experiment_id}"
print(f"View in MLflow: {eval_url}")
```

### Adding Feedback to Traces (Live Demo)

**If a booth visitor says "that's a great answer":**

```python
# Get the trace from that query
trace = mlflow.get_last_active_trace()

# Log feedback
mlflow.log_feedback(
    request_id=trace.info.request_id,
    feedback={"rating": 5, "comment": "Booth visitor approval!"},
    source="conference-demo"
)

print("Feedback logged to MLflow!")
```

---

## Contact & Support

**For demo issues during the conference:**
- Check this guide's troubleshooting section
- Review `BOOTH_SETUP.md` verification steps
- Ping [your team's Slack channel]

**For questions about the demo:**
- GitHub repo: [link]
- Databricks docs: https://docs.databricks.com/en/generative-ai/agent-bricks/
- Community forums: https://community.databricks.com/

---

**Good luck with your demos! 🐝🍯**
