
import os
import json
import uuid
from typing import List
from databricks.sdk import WorkspaceClient
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Config matching default arxiv_demo config
CATALOG = os.environ.get("ARXIV_CATALOG", "arxiv_demo")
SCHEMA = os.environ.get("ARXIV_SCHEMA", "main")
TABLE_NAME = "eval_questions"
FULL_TABLE_NAME = f"{CATALOG}.{SCHEMA}.{TABLE_NAME}"
DATASET_PATH = "evaluation_dataset.json"

def main():
    print(f"Preparing to populate {FULL_TABLE_NAME}...")
    
    # 1. Load Data
    if not os.path.exists(DATASET_PATH):
        print(f"Error: {DATASET_PATH} not found.")
        return

    with open(DATASET_PATH, "r") as f:
        data = json.load(f)
    
    print(f"Loaded {len(data)} items from {DATASET_PATH}")

    # 2. Drop and Create Table
    # Using SQL for simplicity with complex types (arrays)
    profile = os.environ.get("DATABRICKS_PROFILE", "default")
    print(f"Using Databricks profile: {profile}")
    client = WorkspaceClient(profile=profile)
    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not warehouse_id:
        print("Error: DATABRICKS_WAREHOUSE_ID env var not set.")
        return

    print("Recreating table...")
    create_sql = f"""
    CREATE OR REPLACE TABLE {FULL_TABLE_NAME} (
        eval_id STRING,
        request STRING,
        guidelines ARRAY<STRING>,
        metadata STRING,
        tags STRING
    )
    """
    
    try:
        client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=create_sql,
            wait_timeout="30s"
        )
        print("Table created successfully.")
    except Exception as e:
        print(f"Error creating table: {e}")
        return

    # 3. Insert Data
    print("Inserting data...")
    
    values_list = []
    for item in data:
        eval_id = str(uuid.uuid4())
        request = item["question"].replace("'", "''") # Escape single quotes
        ground_truth = item["ground_truth"].replace("'", "''")
        
        # Guidelines as array of strings
        # "Correct answer should include: ..."
        guidelines_val = f"array('The answer should cover the following points: {ground_truth}')"
        
        # Metadata json string
        metadata_val = "'{}'" 
        
        # Tags string
        tags_val = "'arxiv_demo'"

        values_list.append(
            f"('{eval_id}', '{request}', {guidelines_val}, {metadata_val}, {tags_val})"
        )

    # Batch insert (avoid huge single statement if possible, but 10-20 items is fine)
    # Databricks SQL INSERT VALUES supports multiple rows
    
    values_sql = ",\n".join(values_list)
    insert_sql = f"INSERT INTO {FULL_TABLE_NAME} VALUES {values_sql}"
    
    try:
        client.statement_execution.execute_statement(
            warehouse_id=warehouse_id,
            statement=insert_sql,
            wait_timeout="50s"
        )
        print(f"Successfully inserted {len(values_list)} records.")
    except Exception as e:
        print(f"Error inserting data: {e}")
        print("SQL Fragment:", insert_sql[:500])

if __name__ == "__main__":
    main()
