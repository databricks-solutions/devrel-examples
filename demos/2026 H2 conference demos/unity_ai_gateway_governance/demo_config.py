"""Portable configuration for the Unity AI Gateway conference demo."""

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Raised when the demo cannot start with the supplied configuration."""


@dataclass(frozen=True)
class DemoConfig:
    host: str
    token: str
    claude_model_service: str
    claude_model: str
    openai_model_service: str
    openai_model: str
    gemini_model_service: str
    gemini_model: str
    uc_catalog: str
    mlflow_schema: str
    experiment_name: str
    clean_per_agent: int

    @classmethod
    def from_values(
        cls, host: str, token: str, values: Mapping[str, str | None]
    ) -> "DemoConfig":
        """Build and validate configuration from environment or widget values."""

        def value(name: str, default: str = "") -> str:
            raw = values.get(name)
            return str(raw).strip() if raw is not None else default

        clean_raw = value("CLEAN_PER_AGENT", "10")
        try:
            clean_per_agent = int(clean_raw)
        except ValueError as exc:
            raise ConfigurationError("CLEAN_PER_AGENT must be an integer from 1 to 15") from exc

        config = cls(
            host=host.strip().rstrip("/"),
            token=token.strip(),
            claude_model_service=value("CLAUDE_MODEL_SERVICE"),
            claude_model=value("CLAUDE_MODEL", "databricks-claude-opus-4-8"),
            openai_model_service=value("OPENAI_MODEL_SERVICE"),
            openai_model=value("OPENAI_MODEL", "databricks-gpt-5-6-sol"),
            gemini_model_service=value("GEMINI_MODEL_SERVICE"),
            gemini_model=value("GEMINI_MODEL", "databricks-gemini-3-6-flash"),
            uc_catalog=value("UC_CATALOG"),
            mlflow_schema=value("MLFLOW_SCHEMA"),
            experiment_name=value("MLFLOW_EXPERIMENT_NAME"),
            clean_per_agent=clean_per_agent,
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Fail before any gateway or MLflow calls when configuration is incomplete."""
        errors = []
        parsed_host = urlparse(self.host)
        if parsed_host.scheme not in {"http", "https"} or not parsed_host.netloc:
            errors.append("DATABRICKS_HOST must be a full http(s) workspace URL")
        if not self.token:
            errors.append("DATABRICKS_TOKEN is missing")

        services = {
            "CLAUDE_MODEL_SERVICE": self.claude_model_service,
            "OPENAI_MODEL_SERVICE": self.openai_model_service,
            "GEMINI_MODEL_SERVICE": self.gemini_model_service,
        }
        for name, service in services.items():
            parts = service.split(".")
            if len(parts) != 3 or not all(parts):
                errors.append(f"{name} must use catalog.schema.service format")

        if not self.uc_catalog:
            errors.append("UC_CATALOG is missing")
        if not self.mlflow_schema:
            errors.append("MLFLOW_SCHEMA is missing")
        if not self.experiment_name.startswith("/"):
            errors.append("MLFLOW_EXPERIMENT_NAME must be an absolute workspace path")
        if not 1 <= self.clean_per_agent <= 15:
            errors.append("CLEAN_PER_AGENT must be from 1 to 15")

        if errors:
            formatted = "\n".join(f"- {error}" for error in errors)
            raise ConfigurationError(f"Demo configuration is incomplete:\n{formatted}")

    @property
    def providers(self) -> dict[str, tuple[str, str]]:
        return {
            "claude": (self.claude_model_service, self.claude_model),
            "openai": (self.openai_model_service, self.openai_model),
            "gemini": (self.gemini_model_service, self.gemini_model),
        }

    @property
    def gateway_url(self) -> str:
        return f"{self.host}/ai-gateway/mlflow/v1/chat/completions"
