from gateway_config import _routed_model_name


def test_reads_pay_per_token_backing_model_instead_of_destination_label():
    destination = {
        "name": "claude",
        "pay_per_token_config": {
            "model": "models/system.ai.databricks-claude-opus-4-8"
        },
    }

    assert _routed_model_name(destination) == "databricks-claude-opus-4-8"


def test_falls_back_to_destination_name_for_older_responses():
    assert _routed_model_name({"name": "system.ai.gpt-5"}) == "gpt-5"
