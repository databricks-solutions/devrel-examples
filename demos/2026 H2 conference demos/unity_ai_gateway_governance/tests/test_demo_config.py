import pytest

from demo_config import ConfigurationError, DemoConfig

BASE_VALUES = {
    "CLAUDE_MODEL_SERVICE": "demo.gateway.claude",
    "OPENAI_MODEL_SERVICE": "demo.gateway.openai",
    "GEMINI_MODEL_SERVICE": "demo.gateway.gemini",
    "UC_CATALOG": "demo",
    "MLFLOW_SCHEMA": "traces",
    "MLFLOW_EXPERIMENT_NAME": "/Users/presenter@example.com/unity-ai-gateway-demo",
}


def test_builds_portable_config_with_defaults():
    config = DemoConfig.from_values(
        "https://workspace.cloud.databricks.com/", "token", BASE_VALUES
    )

    assert config.host == "https://workspace.cloud.databricks.com"
    assert config.clean_per_agent == 10
    assert config.gateway_url.endswith("/ai-gateway/mlflow/v1/chat/completions")
    assert config.providers["claude"][0] == "demo.gateway.claude"


def test_reports_all_missing_required_values_before_network_calls():
    with pytest.raises(ConfigurationError) as exc_info:
        DemoConfig.from_values("", "", {})

    message = str(exc_info.value)
    assert "DATABRICKS_HOST" in message
    assert "DATABRICKS_TOKEN" in message
    assert "CLAUDE_MODEL_SERVICE" in message
    assert "OPENAI_MODEL_SERVICE" in message
    assert "GEMINI_MODEL_SERVICE" in message
    assert "UC_CATALOG" in message
    assert "MLFLOW_SCHEMA" in message
    assert "MLFLOW_EXPERIMENT_NAME" in message


@pytest.mark.parametrize("service", ["", "catalog.schema", "catalog..service", "a.b.c.d"])
def test_rejects_invalid_model_service_names(service):
    values = {**BASE_VALUES, "CLAUDE_MODEL_SERVICE": service}

    with pytest.raises(ConfigurationError, match="catalog.schema.service"):
        DemoConfig.from_values("https://workspace.example.com", "token", values)


@pytest.mark.parametrize("volume", ["0", "16", "many"])
def test_rejects_invalid_clean_request_volume(volume):
    values = {**BASE_VALUES, "CLEAN_PER_AGENT": volume}

    with pytest.raises(ConfigurationError, match="CLEAN_PER_AGENT"):
        DemoConfig.from_values("https://workspace.example.com", "token", values)
