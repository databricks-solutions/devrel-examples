# 2026 H2 conference demos

This folder contains two conference demos. Use the summaries below to choose one, then follow its linked presenter or setup guide for the full walkthrough.

## Omnigent conference demo

The Omnigent demo shows how a meta-harness coordinates multiple coding agents to investigate, implement, and review fixes to a deliberately naive GitHub issue-triage client. It is designed for a presenter-led booth conversation focused on agent graphs, isolated work, review, policies, and governed model usage—not for attendee hands-on work.

**Get started:** Open [`omnigent/PRESENTER.md`](omnigent/PRESENTER.md) and complete **Before the event**. For a managed run, start a new Omnigent session with Polly and a Databricks Sandbox, point it at this repository, and paste Prompt 0 from the guide. For a local fallback, follow the guide's **OSS fallback** instructions.

## Unity AI Gateway governance demo

The Unity AI Gateway demo shows how teams can route coding agents across Claude, OpenAI, and Gemini through governed Unity Catalog model services, then demonstrate guardrails, rate limits, audit data, usage attribution, MLflow traces, and a shared dashboard in one notebook.

**Get started:** First create the three model services described in [`unity_ai_gateway_governance/README.md`](unity_ai_gateway_governance/README.md). Then launch the notebook locally:

```bash
cd 'demos/2026 H2 conference demos/unity_ai_gateway_governance'
cp env-template .env  # fill in the workspace and model-service values
uv sync
uv run jupyter notebook ai_gateway_demo.ipynb
```

To run it in Databricks instead, authenticate with the Databricks CLI, then run `databricks bundle validate` and `databricks bundle deploy` from the same directory. The demo README includes the required service settings and the eight-act presenter flow.
