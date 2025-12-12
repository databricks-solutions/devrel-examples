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

**Web Terminal**:
1.  Clone the repo into Databricks.
2.  Open a Web Terminal.
3.  Install dependencies: `pip install -r requirements.txt` (or install manually).
4.  Run: `streamlit run app/main.py`.

**Notebook**:
1.  Create a notebook in the `app` directory.
2.  Run the app inline:
    ```python
    from streamlit.web.cli import main
    import sys
    sys.argv = ["streamlit", "run", "app/main.py"]
    main()
    ```
    *Note: Streamlit inside notebooks has varying support depending on the runtime version.*

## Databricks Apps (Upcoming)
Support for deploying this strictly as a [Databricks App](https://docs.databricks.com/en/dev-tools/databricks-apps/index.html) is coming soon.

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
*   `src/arxiv_demo/`: Core logic for ingestion, parsing, and KIE.
*   `scripts/`: Utility scripts for data setup and maintenance.
*   `evaluation_dataset.json`: Source data for evaluation questions.
