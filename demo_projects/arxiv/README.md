# Arxiv Paper Analysis Demo

A Databricks AI demo for analyzing Arxiv papers using Knowledge Assistant and ai_parse_document.

**Why this matters**: A Knowledge Assistant populated with random data isn't helpful. This project demonstrates a workflow for **curating** a knowledge base—searching, selecting, and extracting specific papers—to create an assistant that is highly relevant to your specific research interests. This project demonstrates:

*   **Ingestion**: Searching Arxiv, downloading PDFs, and uploading to Unity Catalog Volumes.
*   **Parsing**: Using `ai_parse_document` to extract text from PDFs.
*   **Structured Extraction**: Using Agent Bricks (KIE) to extract structured fields (methodology, limitations, etc.).
*   **Knowledge Assistant**: Using the native Databricks Knowledge Assistant to answer questions with citations.
*   **Evaluation**: Evaluating the assistant using the Knowledge Assistant Evaluation UI with a ground-truth dataset.

## Prerequisites

*   Databricks Workspace with Unity Catalog enabled.
*   Python 3.10+.
*   [uv](https://github.com/astral-sh/uv) (recommended) or `pip`.

## Authentication Setup

This project uses the Databricks SDK, which supports multiple authentication methods.

**Option 1: Databricks CLI Profile (Recommended for Local Dev)**
If you have the [Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/index.html) installed:
1.  Run `databricks configure` and follow the prompts.
2.  Set `DATABRICKS_PROFILE=default` (or your profile name) in `.env`.

**Option 2: Environment Variables**
Set `DATABRICKS_HOST` and `DATABRICKS_TOKEN` directly in your `.env` file.

**Option 3: Databricks Notebook/Runtime**
If running this code on a Databricks cluster (e.g. via Web Terminal or Notebook), authentication is handled automatically. You generally **do not** need to set host/token/profile variables.

## Setup

1.  **Clone the repository**:
    ```bash
    git clone <repo-url>
    cd demo_projects/arxiv
    ```

2.  **Install dependencies**:
    ```bash
    uv sync
    # Or with pip: pip install -r requirements.txt (if generated)
    ```

3.  **Configure Environment**:
    Create a `.env` file in the root directory:
    ```bash
    cp .env.example .env
    ```
    Edit `.env` and provide your Databricks credentials and configuration:
    ```env
    DATABRICKS_WAREHOUSE_ID=<your-sql-warehouse-id>

    # Authentication (Choose one)
    # 1. Use local Databricks CLI profile (Recommended)
    DATABRICKS_PROFILE=default

    # 2. Or explicit credentials
    # DATABRICKS_HOST=https://<your-workspace>.cloud.databricks.com
    # DATABRICKS_TOKEN=<your-pat-token>
    
    # Optional overrides
    ARXIV_CATALOG=arxiv_demo
    ARXIV_SCHEMA=main
    ARXIV_VOLUME=pdfs
    ```

## Agent Setup

Before running the app, you need to create two agents in Databricks: a **Knowledge Assistant** (for RAG) and a **KIE Agent** (for extraction).

### 1. Create Knowledge Assistant
1.  Navigate to **Agents** > **Create Agent**.
2.  Select **Knowledge Source**: Unity Catalog Volume (`arxiv_demo.main.pdfs`).
3.  Name it: `arxiv-papers`.
4.  Deploy the agent and copy the **Serving Endpoint Name** (e.g., `agents_arxiv-papers`).
5.  Set `KA_ENDPOINT=agents_arxiv-papers` in your `.env`.

### 2. Create KIE Agent (Agent Bricks)
1.  Navigate to **Agents** > **Create Agent**.
2.  Select **Pattern**: "Key Information Extraction" (or similar Agent Brick).
3.  Name it: `arxiv-kie`.
4.  Use the following JSON Schema:
    ```json
    {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "title": "Generated Schema",
      "type": "object",
      "properties": {
        "affiliation": {
          "description": "The \"affiliation\" field must contain the name of the organization, institution, or company with which the authors are associated. This information should be extracted as a string and may include department names, university names, or corporate entities. Ensure that the extracted content is precise and accurately reflects the authors' affiliations as stated in the source document.",
          "anyOf": [
            { "type": "string" },
            { "type": "null" }
          ]
        },
        "contributions": {
          "description": "The \"contributions\" field must contain an array of strings that explicitly list the contributions made by the authors to the dataset or research presented in the document. Each entry in the array should clearly articulate a specific contribution, such as data collection, analysis, or writing, and should not include vague or general statements. If no contributions are provided, this field should be set to null.",
          "anyOf": [
            { "type": "array", "items": { "type": "string" } },
            { "type": "null" }
          ]
        },
        "authors": {
          "description": "The \"authors\" field must contain an array of strings, each representing the full name of an author associated with the dataset or research work. The names should be formatted as \"First Last\" without any titles or affiliations included. This field is required to accurately attribute contributions to the respective authors in the context of the dataset.",
          "anyOf": [
            { "type": "array", "items": { "type": "string" } },
            { "type": "null" }
          ]
        },
        "title": {
          "description": "The \"title\" field must contain the complete title of the document or work being referenced. It should be a string that accurately reflects the main subject or focus of the content, without any abbreviations or alterations. Ensure that the title is extracted as it appears in the source material, maintaining proper capitalization and punctuation.",
          "anyOf": [
            { "type": "string" },
            { "type": "null" }
          ]
        },
        "methodology": {
          "type": "string",
          "description": "The \"methodology\" field must describe the specific research methods, experimental designs, techniques, or approaches used to conduct the study. This includes data collection procedures, model architectures, training strategies, evaluation protocols, and any novel technical contributions to the research process itself."
        },
        "limitations": {
          "type": "array",
          "description": "The \"limitations\" field must contain an array of strings listing the acknowledged weaknesses, constraints, and boundaries of the research. This includes scope restrictions, potential biases in data or methods, scenarios where the approach may fail, computational requirements, and areas identified for future improvement.",
          "items": { "type": "string" }
        },
        "topics": {
          "type": "array",
          "description": "The \"topics\" field must list the main subject areas, research themes, and technical domains covered by the paper. This includes specific tasks addressed (e.g., question answering, code generation), model types (e.g., transformer, diffusion), and application areas (e.g., healthcare, robotics).",
          "items": { "type": "string" }
        }
      },
      "required": [
        "affiliation",
        "contributions",
        "authors",
        "title",
        "methodology",
        "limitations",
        "topics"
      ]
    }
    ```
5.  Deploy the agent and copy the **Serving Endpoint Name**.
6.  Set `KIE_ENDPOINT=agents_arxiv-kie` in your `.env`.

### Finding Endpoint Names

After deploying your agents, you can find the endpoint names in several ways:

1. **Agents UI**: Go to **Machine Learning** > **Agents** > select your agent > look for "Serving Endpoint" in the details panel
2. **Serving Endpoints UI**: Go to **Machine Learning** > **Serving** > find your agent's endpoint (typically prefixed with `agents_`)
3. **CLI**: Run `databricks serving-endpoints list` and look for endpoints matching your agent names

The endpoint names are used in:
- `.env` file for local development (`KA_ENDPOINT`, `KIE_ENDPOINT`)
- `app.yaml` for Databricks Apps deployment
- `databricks.yml` variables for DAB-based deployment

## Initialization

Before running the app or evaluation, you need to populate your Unity Catalog Volume and Tables.

### 1. Ingest Golden Set Papers
Download a curated set of seminal LLM Agent papers (ReAct, Reflexion, Voyager, etc.) to use as the base knowledge.

```bash
uv run python scripts/ingest_golden_set.py
```
*This uploads PDFs to `/Volumes/arxiv_demo/main/pdfs/`.*

### 2. Create Evaluation Dataset
Create the Unity Catalog table required for the Knowledge Assistant Evaluation UI.

```bash
uv run python scripts/create_eval_table.py
```
*Creates `arxiv_demo.main.eval_questions` populated with 5 evaluation questions matching the golden set papers.*

## Running the App

There are three ways to run this application:

| Method | Best For | Requirements |
|--------|----------|--------------|
| **Local Execution** | Development & testing | Local Python environment, Databricks CLI profile |
| **Databricks Apps (DAB)** | Production deployment | Databricks CLI, DAB bundles |
| **Runbook** | Interactive setup & learning | Databricks notebook environment |

---

### Method 1: Local Execution

Run the Streamlit app locally for development:

```bash
# Ensure .env is configured with your endpoints
uv run streamlit run app/main.py
```

Requirements:
- `.env` file with `DATABRICKS_PROFILE`, `KA_ENDPOINT`, `KIE_ENDPOINT`, `DATABRICKS_WAREHOUSE_ID`
- Databricks CLI profile configured

---

### Method 2: Databricks Apps Deployment (DAB)

Deploy as a [Databricks App](https://docs.databricks.com/en/dev-tools/databricks-apps/index.html) for production use. This method uses Databricks Asset Bundles (DAB) for declarative deployment with automatic permission management.

### How Authentication Works

Databricks Apps use **service principal OAuth** for authentication. When your app runs:

1. The runtime injects `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, and `DATABRICKS_HOST` environment variables
2. The Databricks SDK automatically uses these credentials when you create a `WorkspaceClient()` without arguments
3. For serving endpoints, use `ws.serving_endpoints.get_open_ai_client()` which handles OAuth token exchange automatically

**Key insight**: You don't need to manage tokens manually. The SDK handles everything if you:
- Use `WorkspaceClient()` without explicit credentials
- Use the SDK's built-in `get_open_ai_client()` for OpenAI-compatible endpoints

### Prerequisites

Before deploying, ensure you have:

1. **Databricks CLI** configured with your workspace profile
2. **Unity Catalog resources** created:
   - Catalog: `arxiv_demo`
   - Schema: `arxiv_demo.main`
   - Volume: `arxiv_demo.main.pdfs`
3. **Agents deployed** with serving endpoints:
   - Knowledge Assistant endpoint (e.g., `ka-xxxxx-endpoint`)
   - KIE Agent endpoint (e.g., `kie-xxxxx-endpoint`)
4. **SQL Warehouse** available (for `ai_parse_document`)

### Configuration Files

**`app.yaml`** - Defines the app runtime:
```yaml
command:
  - streamlit
  - run
  - app/main.py
  - --server.port
  - "8000"
  - --server.address
  - "0.0.0.0"
env:
  # Required for local package imports
  - name: PYTHONPATH
    value: /app/python/source_code
  # Auth - automatically set by Databricks Apps runtime
  - name: DATABRICKS_HOST
    valueFrom: host
  # Unity Catalog resources
  - name: ARXIV_CATALOG
    value: arxiv_demo
  - name: ARXIV_SCHEMA
    value: main
  - name: ARXIV_VOLUME
    value: pdfs
  # SQL Warehouse for ai_parse_document
  - name: DATABRICKS_WAREHOUSE_ID
    value: <your-warehouse-id>
  # Agent endpoints
  - name: KIE_ENDPOINT
    value: <your-kie-endpoint-name>
  - name: KA_ENDPOINT
    value: <your-ka-endpoint-name>
```

**`databricks.yml`** - DAB bundle configuration with variables and resources:
```yaml
bundle:
  name: arxiv-demo

# User-configurable variables (update these for your environment)
variables:
  ka_endpoint:
    description: "Knowledge Assistant serving endpoint name"
    default: "REPLACE_WITH_YOUR_KA_ENDPOINT"
  kie_endpoint:
    description: "KIE Agent serving endpoint name"
    default: "REPLACE_WITH_YOUR_KIE_ENDPOINT"
  warehouse_id:
    description: "SQL Warehouse ID"
    default: "REPLACE_WITH_YOUR_WAREHOUSE_ID"
  catalog:
    default: "arxiv_demo"
  schema:
    default: "main"
  volume:
    default: "pdfs"

resources:
  apps:
    arxiv-app:
      name: arxiv-app
      description: "Arxiv Knowledge Assistant Curator App"
      source_code_path: .
      # App resources - permissions automatically granted to app's service principal
      resources:
        - name: "ka-endpoint"
          serving_endpoint:
            name: ${var.ka_endpoint}
            permission: "CAN_QUERY"
        - name: "kie-endpoint"
          serving_endpoint:
            name: ${var.kie_endpoint}
            permission: "CAN_QUERY"
        - name: "sql-warehouse"
          sql_warehouse:
            id: ${var.warehouse_id}
            permission: "CAN_USE"
        - name: "pdfs-volume"
          uc_securable:
            securable_full_name: ${var.catalog}.${var.schema}.${var.volume}
            securable_type: VOLUME
            permission: WRITE_VOLUME

targets:
  dev:
    mode: development
    default: true
    workspace:
      profile: default  # Change to your CLI profile
```

### How Resources Work

When you declare resources in `databricks.yml`, Databricks automatically:

1. Creates a service principal for your app
2. Grants the specified permissions to that service principal
3. Makes resource metadata available via `valueFrom` in `app.yaml` (optional)

**No manual permission scripts needed!** The bundle handles everything during `databricks bundle deploy`.

Available resource types:
- `serving_endpoint`: Model serving endpoints (permission: `CAN_QUERY` or `CAN_MANAGE`)
- `sql_warehouse`: SQL warehouses (permission: `CAN_USE` or `CAN_MANAGE`)
- `uc_securable`: Unity Catalog objects like volumes (permission: `READ_VOLUME` or `WRITE_VOLUME`)

### Deploy the App

**Step 1: Configure your settings**

Edit `databricks.yml` and `app.yaml` with your endpoint names and warehouse ID:
- `ka_endpoint`: Your Knowledge Assistant endpoint (e.g., `agents_arxiv-papers`)
- `kie_endpoint`: Your KIE Agent endpoint (e.g., `agents_arxiv-kie`)
- `warehouse_id`: Your SQL Warehouse ID (from SQL Warehouses > Connection Details)

**Step 2: Authenticate and deploy**

```bash
# Authenticate with the Databricks CLI
databricks auth login --profile <your-profile>

# Deploy the bundle (uses defaults from databricks.yml)
databricks bundle deploy --profile <your-profile>

# Or override variables at deploy time:
databricks bundle deploy --profile <your-profile> \
  --var ka_endpoint=agents_arxiv-papers \
  --var kie_endpoint=agents_arxiv-kie \
  --var warehouse_id=abc123def456

# Start the app
databricks apps start arxiv-app --profile <your-profile>

# Check app status
databricks apps get arxiv-app --profile <your-profile>
```

The app URL will be displayed in the output (e.g., `https://arxiv-app-xxxxx.aws.databricksapps.com`).

---

### Method 3: Runbook Deployment

The `Runbook.ipynb` notebook provides an interactive, step-by-step approach to setting up and deploying the app directly from Databricks.

**What the Runbook provides:**
1. Interactive widgets for configuring endpoint names and warehouse IDs
2. Guided setup of Unity Catalog resources (catalog, schema, volume, tables)
3. Paper ingestion and agent creation instructions
4. App deployment with automatic configuration updates

**To use the Runbook:**
1. Import `Runbook.ipynb` into your Databricks workspace
2. Attach to a cluster with the Databricks CLI installed
3. Run through each section, filling in widgets as prompted
4. The Runbook will update `app.yaml` and `databricks.yml` with your settings before deployment

This method is recommended for first-time setup or learning, as it provides context and verification at each step.

### Dual-Mode Authentication (Local + Deployed)

The app supports both local development and Databricks Apps deployment:

```python
from databricks.sdk import WorkspaceClient
from arxiv_demo.config import DEFAULT_CONFIG

# Works in both environments:
# - Local: Uses profile from DATABRICKS_PROFILE env var
# - Databricks Apps: Uses injected OAuth credentials
ws_client = WorkspaceClient(profile=DEFAULT_CONFIG.profile)

# For serving endpoints, use the SDK's built-in method:
openai_client = ws_client.serving_endpoints.get_open_ai_client()
```

The SDK automatically detects the environment and uses the appropriate credentials.

## Knowledge Assistant Evaluation

To evaluate your agent using the data you initialized:

1.  **Create a Knowledge Assistant**:
    *   In Databricks, go to **Agents** > **Create Agent**.
    *   Select **Knowledge Source**: Unity Catalog Volume (`arxiv_demo.main.pdfs`).
    *   Name it (e.g., `arxiv-agent`).
    *   Deploy the agent.

2.  **Run Evaluation**:
    *   Go to the **Evaluation** tab in your agent's page (or the dedicated Evaluation UI).
    *   Click **Import** > **Unity Catalog Table**.
    *   Select `arxiv_demo.main.eval_questions`.
    *   Map the columns (Eval ID, Request, Guidelines, etc.).
    *   Run the evaluation.
    *   Review the scores and "LLM as a Judge" feedback.

## Project Structure

```
arxiv/
├── app/                    # Streamlit application
│   └── main.py             # Main app entry point
├── arxiv_demo/             # Core library
│   ├── config.py           # Configuration management
│   ├── ingestion.py        # Arxiv search, download, parsing, KIE
│   └── knowledge_assistant.py  # KA client for chat
├── scripts/                # Setup utilities
│   ├── ingest_golden_set.py    # Download curated papers
│   └── create_eval_table.py    # Create evaluation dataset
├── app.yaml                # Databricks Apps runtime config
├── databricks.yml          # DAB bundle configuration
├── Runbook.ipynb           # Interactive setup notebook
├── evaluation_dataset.json # Source evaluation questions
└── .env.example            # Environment template
```
