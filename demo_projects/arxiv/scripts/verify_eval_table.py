
import os
from databricks.sdk import WorkspaceClient
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CATALOG = os.environ.get("ARXIV_CATALOG", "arxiv_demo")
SCHEMA = os.environ.get("ARXIV_SCHEMA", "main")
TABLE_NAME = "eval_questions"
FULL_TABLE_NAME = f"{CATALOG}.{SCHEMA}.{TABLE_NAME}"

def main():
    profile = os.environ.get("DATABRICKS_PROFILE", "default")
    print(f"Using profile: {profile}")
    client = WorkspaceClient(profile=profile)
    
    print(f"Verifying {FULL_TABLE_NAME}...")
    try:
        response = client.statement_execution.execute_statement(
            warehouse_id=os.environ.get("DATABRICKS_WAREHOUSE_ID"),
            statement=f"SELECT * FROM {FULL_TABLE_NAME} LIMIT 5",
            wait_timeout="50s"
        )
        if response.result and response.result.data_array:
            print("Success! Found rows:")
            for row in response.result.data_array:
                print(row)
        else:
            print("Table found but no data returned.")
    except Exception as e:
        print(f"Verification failed: {e}")

if __name__ == "__main__":
    main()
