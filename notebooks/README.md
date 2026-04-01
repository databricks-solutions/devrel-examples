# Databricks DevRel Example Notebooks

A collection of notebooks demonstrating Databricks features and integrations.

## Notebooks

### `nbs/` — Databricks Platform

| Notebook | Description |
|----------|-------------|
| [ai_sql_functions](nbs/ai_sql_functions.ipynb) | Query Foundation Models with SQL using `ai_query` |
| [fast_classification_provisioned](nbs/fast_classification_provisioned.ipynb) | High-throughput text classification with Provisioned Throughput |
| [fm_api_mlflow_prompt_eng](nbs/fm_api_mlflow_prompt_eng.ipynb) | Compare models and prompts with the MLflow Prompt Engineering UI |
| [fm_api_openai_sdk](nbs/fm_api_openai_sdk.ipynb) | Use the Foundation Model API with the OpenAI Python SDK |
| [fm_api_outside_db](nbs/fm_api_outside_db.ipynb) | Call the Foundation Model API from outside Databricks |
| [intro_generation_parameters](nbs/intro_generation_parameters.ipynb) | Control model behavior with temperature, top_p, top_k, and more |
| [manage_chat_sessions](nbs/manage_chat_sessions.ipynb) | Manage chat sessions with ChatSession and custom history |
| [playground](nbs/playground.ipynb) | Test and compare LLMs in the Databricks AI Playground |
| [sam2-on-databricks](nbs/sam2-on-databricks.ipynb) | Run SAM2 video object segmentation on Databricks |
| [serve_marketplace](nbs/serve_marketplace.ipynb) | Deploy Marketplace models with Delta Sharing and Model Serving |
| [streaming_outputs](nbs/streaming_outputs.ipynb) | Stream responses from Foundation Model API models |
| [vector_search_fm_api](nbs/vector_search_fm_api.ipynb) | Set up Vector Search with Foundation Model API embeddings |
| [AI Gateway helper notebook](nbs/AI%20Gateway%20helper%20notebook%20%F0%9F%91%A9%F0%9F%8F%BC%E2%80%8D%F0%9F%8F%AB.ipynb) | Query system tables for AI serving endpoint usage |
| [Connect to more data with Lakehouse Federation](nbs/%F0%9F%A4%9D%20Connect%20to%20more%20data%20with%20Lakehouse%20Federation.ipynb) | Query external databases via Lakehouse Federation |
| [Current LDN 2025 transformWithState](nbs/Current%20LDN%202025%20transformWithState.ipynb) | Stateful Structured Streaming with transformWithStateInPandas |
| [Data Engineering SQL Holiday Specials](nbs/%F0%9F%8E%84Data%20Engineering%20SQL%20Holiday%20Specials.ipynb) | New SQL features from late 2024: materialized views, federation, and more |
| [Ham Sandwiches Custom Config](nbs/%F0%9F%A5%AA%20Ham%20Sandwiches%20Custom%20Config%20for%20Spark%20%26%20Delta.ipynb) | Pass variables between languages and add custom Delta config |

### `mlflow/` — OSS AI / MLflow

| Notebook | Description |
|----------|-------------|
| [2024-11-27-dspy](mlflow/2024-11-27-dspy.ipynb) | Build and optimize LLM programs with DSPy and MLflow |
| [gemini-trace-tool](mlflow/gemini-trace-tool.ipynb) | MLflow tracing with Gemini 2.0 Flash and tool calling |

## How to Use

### Import individual notebooks

In your Databricks workspace, go to the workspace browser, select **Import** (from the kebab menu or right-click menu), and paste the raw GitHub URL of the notebook you want to import.

### Clone the repository

Navigate to **Repos** in your Databricks workspace, click **Add Repo**, and enter:

```
https://github.com/databricks-solutions/devrel-examples
```

All notebooks are in the `notebooks/` directory.
