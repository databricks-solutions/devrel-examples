"""
Centralized configuration for arxiv demo.

Configuration is read from environment variables.
Create a .env file or set env vars directly.
"""

import os
from dataclasses import dataclass, field

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_env(key: str, default: str | None = None, required: bool = False) -> str | None:
    """Get environment variable with optional default."""
    value = os.environ.get(key, default)
    if required and not value:
        raise ValueError(f"Required environment variable {key} is not set")
    return value


@dataclass
class DatabricksConfig:
    """Databricks resource configuration."""

    # Unity Catalog
    catalog: str = field(default_factory=lambda: _get_env("ARXIV_CATALOG", "arxiv_demo"))
    schema: str = field(default_factory=lambda: _get_env("ARXIV_SCHEMA", "main"))
    volume: str = field(default_factory=lambda: _get_env("ARXIV_VOLUME", "pdfs"))

    # Databricks CLI profile
    profile: str | None = field(default_factory=lambda: _get_env("DATABRICKS_PROFILE"))

    # SQL Warehouse ID (required)
    warehouse_id: str = field(default_factory=lambda: _get_env("DATABRICKS_WAREHOUSE_ID", ""))

    # Knowledge Assistant endpoint (optional, set after creating via UI)
    ka_endpoint: str | None = field(default_factory=lambda: _get_env("KA_ENDPOINT"))

    # KIE Agent endpoint (required for extraction)
    kie_endpoint: str = field(default_factory=lambda: _get_env("KIE_ENDPOINT", ""))

    @property
    def volume_path(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema}/{self.volume}"

    @property
    def full_schema(self) -> str:
        return f"{self.catalog}.{self.schema}"

    def validate(self) -> list[str]:
        """Check for missing required config. Returns list of missing items."""
        missing = []
        if not self.warehouse_id:
            missing.append("DATABRICKS_WAREHOUSE_ID")
        if not self.kie_endpoint:
            missing.append("KIE_ENDPOINT")
        return missing


# Default configuration instance
DEFAULT_CONFIG = DatabricksConfig()
