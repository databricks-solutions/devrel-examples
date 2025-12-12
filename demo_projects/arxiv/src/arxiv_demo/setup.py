"""
Setup and initialization for arxiv demo.

Handles creating all Databricks resources (schema, volume, tables).
Catalog must be created manually via UI on some workspaces.
"""

from pathlib import Path

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import VolumeType

from .config import DEFAULT_CONFIG, DatabricksConfig


class DatabricksSetup:
    """Set up Databricks resources for arxiv demo."""

    def __init__(self, config: DatabricksConfig | None = None):
        self.config = config or DEFAULT_CONFIG
        self._client: WorkspaceClient | None = None

    @property
    def client(self) -> WorkspaceClient:
        if self._client is None:
            self._client = WorkspaceClient(profile=self.config.profile)
        return self._client

    def check_catalog_exists(self) -> bool:
        """Check if catalog exists."""
        try:
            self.client.catalogs.get(self.config.catalog)
            return True
        except Exception:
            return False

    def create_schema(self) -> None:
        """Create schema if it doesn't exist."""
        try:
            self.client.schemas.create(
                name=self.config.schema,
                catalog_name=self.config.catalog,
            )
            print(f"Created schema: {self.config.full_schema}")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"Schema exists: {self.config.full_schema}")
            else:
                raise

    def create_volume(self) -> None:
        """Create volume if it doesn't exist."""
        try:
            self.client.volumes.create(
                catalog_name=self.config.catalog,
                schema_name=self.config.schema,
                name=self.config.volume,
                volume_type=VolumeType.MANAGED,
            )
            print(f"Created volume: {self.config.volume_path}")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"Volume exists: {self.config.volume_path}")
            else:
                raise

    def run_sql_file(self, sql_file: Path, warehouse_id: str) -> None:
        """Run a SQL file with variable substitution."""
        sql_content = sql_file.read_text()

        # Substitute variables
        sql_content = sql_content.replace("${catalog}", self.config.catalog)
        sql_content = sql_content.replace("${schema}", self.config.schema)

        # Split into statements and execute
        statements = [s.strip() for s in sql_content.split(";") if s.strip()]

        for stmt in statements:
            if stmt.startswith("--"):
                continue
            try:
                self.client.statement_execution.execute_statement(
                    warehouse_id=warehouse_id,
                    statement=stmt,
                    wait_timeout="30s",
                )
                # Extract first line for logging
                first_line = stmt.split("\n")[0][:60]
                print(f"Executed: {first_line}...")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print(f"Already exists, skipping...")
                else:
                    print(f"Error: {e}")
                    raise

    def setup_all(self, warehouse_id: str) -> None:
        """Run complete setup."""
        print(f"Setting up arxiv demo in {self.config.catalog}...")
        print()

        # Check catalog
        if not self.check_catalog_exists():
            print(f"ERROR: Catalog '{self.config.catalog}' does not exist.")
            print("Please create it via the Databricks UI first.")
            return

        print(f"Using catalog: {self.config.catalog}")

        # Create schema and volume
        self.create_schema()
        self.create_volume()

        # Run SQL scripts
        sql_dir = Path(__file__).parent.parent.parent / "sql"
        sql_files = sorted(sql_dir.glob("*.sql"))

        for sql_file in sql_files:
            print(f"\nRunning {sql_file.name}...")
            self.run_sql_file(sql_file, warehouse_id)

        print("\nSetup complete!")


def main():
    """Run setup with default config."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m arxiv_demo.setup <warehouse_id>")
        print("\nFind your warehouse ID with:")
        print("  dbai sql run --help")
        sys.exit(1)

    warehouse_id = sys.argv[1]
    setup = DatabricksSetup()
    setup.setup_all(warehouse_id)


if __name__ == "__main__":
    main()
