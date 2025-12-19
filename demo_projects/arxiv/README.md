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
    *   Use the following JSON Schema:
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

### Option 1: Local Execution
Run the Streamlit app locally:
```bash
uv run streamlit run app/main.py
```

### Option 2: Run on Databricks
You can run this project directly in a Databricks Notebook or Web Terminal.

**Method A: Databricks Runbook (Recommended)**
Import the notebook at `Runbook.ipynb` into your workspace. It guides you through the entire setup, ingestion, agent creation, and app execution interactively.

**Method B: Web Terminal**:
1.  Clone the repo into Databricks.
2.  Open a Web Terminal.
3.  Install dependencies: `pip install -r requirements.txt` (or install manually).
4.  Run: `streamlit run app/main.py`.

**Method C: Custom Notebook**:
1.  Create a notebook in the `app` directory.
2.  Run the app inline:
    ```python
    from streamlit.web.cli import main
    import sys
    sys.argv = ["streamlit", "run", "app/main.py"]
    main()
    ```
    *Note: Streamlit inside notebooks has varying support depending on the runtime version.*

## Databricks Apps Deployment

Deploy this app as a [Databricks App](https://docs.databricks.com/en/dev-tools/databricks-apps/index.html) for production use.

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

**`databricks.yml`** - DAB bundle configuration:
```yaml
bundle:
  name: arxiv-demo

resources:
  apps:
    arxiv-app:
      name: arxiv-app
      description: "Arxiv Knowledge Assistant Curator App"
      source_code_path: .

targets:
  dev:
    mode: development
    default: true
    workspace:
      profile: <your-profile>
```

### Grant Service Principal Permissions

After deployment, the app's service principal needs permissions to access resources. Run this Python script to grant them programmatically:

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    ServingEndpointAccessControlRequest,
    ServingEndpointPermissionLevel
)
from databricks.sdk.service.sql import (
    WarehouseAccessControlRequest,
    WarehousePermissionLevel
)

w = WorkspaceClient(profile='<your-profile>')

# Get the service principal ID from the app (visible in Databricks Apps UI)
sp_id = '<app-service-principal-id>'  # e.g., '9aecd2a5-df62-4cd1-be6e-0bf784e4bde3'

# 1. Grant CAN_QUERY on serving endpoints
ka_endpoint_id = '<ka-endpoint-guid>'   # Get from: databricks serving-endpoints list
kie_endpoint_id = '<kie-endpoint-guid>'

for endpoint_id in [ka_endpoint_id, kie_endpoint_id]:
    w.serving_endpoints.update_permissions(
        serving_endpoint_id=endpoint_id,
        access_control_list=[
            ServingEndpointAccessControlRequest(
                service_principal_name=sp_id,
                permission_level=ServingEndpointPermissionLevel.CAN_QUERY
            )
        ]
    )

# 2. Grant CAN_USE on SQL Warehouse
warehouse_id = '<your-warehouse-id>'
w.warehouses.update_permissions(
    warehouse_id=warehouse_id,
    access_control_list=[
        WarehouseAccessControlRequest(
            service_principal_name=sp_id,
            permission_level=WarehousePermissionLevel.CAN_USE
        )
    ]
)

# 3. Grant Unity Catalog permissions
stmts = [
    f"GRANT USE CATALOG ON CATALOG arxiv_demo TO `{sp_id}`",
    f"GRANT USE SCHEMA ON SCHEMA arxiv_demo.main TO `{sp_id}`",
    f"GRANT READ VOLUME, WRITE VOLUME ON VOLUME arxiv_demo.main.pdfs TO `{sp_id}`"
]
for stmt in stmts:
    w.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=stmt,
        wait_timeout='30s'
    )

print("Permissions granted!")
```

### Deploy the App

```bash
# Authenticate with the Databricks CLI
databricks auth login --profile <your-profile>

# Deploy the bundle
databricks bundle deploy --profile <your-profile>

# Check app status
databricks apps get arxiv-app --profile <your-profile>
```

The app URL will be displayed in the output (e.g., `https://arxiv-app-xxxxx.aws.databricksapps.com`).

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

*   `app/`: Streamlit application code.
*   `arxiv_demo/`: Core logic for ingestion, parsing, KIE, and evaluation.
*   `scripts/`: Utility scripts for data setup and maintenance.
*   `Runbook.ipynb`: Interactive notebook for setup and running in Databricks.
*   `evaluation_dataset.json`: Source data for evaluation questions.
