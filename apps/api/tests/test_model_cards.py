"""Tests for GET /model-cards/{model} endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient
from reprompt_api.main import app

client = TestClient(app)


def test_get_model_card_claude_resolves_to_anthropic() -> None:
    response = client.get("/model-cards/claude-3-5-sonnet")
    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "anthropic"
    assert data["version"] == 1
    assert "xml" in data["description"].lower() or "XML" in data["description"]
    assert len(data["rules"]) >= 1


def test_get_model_card_gpt_resolves_to_openai() -> None:
    response = client.get("/model-cards/gpt-4o")
    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "openai"
    assert data["version"] == 1


def test_get_model_card_gemini_resolves_to_gemini_family() -> None:
    response = client.get("/model-cards/gemini-2.0-flash")
    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "gemini"
    assert data["version"] == 1
    assert "markdown" in data["description"].lower() or "Markdown" in data["description"]


def test_get_model_card_llama_resolves_to_llama_family() -> None:
    response = client.get("/model-cards/ollama/llama3")
    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "llama"
    assert data["version"] == 1


def test_get_model_card_unknown_resolves_to_generic() -> None:
    response = client.get("/model-cards/some-unknown-model-xyz")
    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "generic"


def test_get_model_card_small_variant_detected() -> None:
    response = client.get("/model-cards/claude-3-5-haiku")
    assert response.status_code == 200
    data = response.json()
    assert data["is_small_variant"] is True


def test_get_model_card_large_variant_not_detected() -> None:
    response = client.get("/model-cards/claude-3-5-sonnet")
    assert response.status_code == 200
    data = response.json()
    assert data["is_small_variant"] is False


def test_get_model_card_rules_have_required_fields() -> None:
    response = client.get("/model-cards/claude-3-5-sonnet")
    assert response.status_code == 200
    data = response.json()
    assert "rules" in data
    assert len(data["rules"]) > 0
    for rule in data["rules"]:
        assert "name" in rule
        assert "description" in rule
        assert "applies_to" in rule
        assert "will_apply" in rule
        assert isinstance(rule["will_apply"], bool)


def test_get_model_card_small_model_applies_terseify() -> None:
    response = client.get("/model-cards/claude-3-5-haiku")
    assert response.status_code == 200
    data = response.json()
    assert data["is_small_variant"] is True
    # Haiku should have terseify rule that will apply (small_only rule + is small)
    terseify = next((r for r in data["rules"] if r["name"] == "terseify_if_small"), None)
    assert terseify is not None
    assert terseify["will_apply"] is True


def test_get_model_card_large_model_does_not_apply_terseify() -> None:
    response = client.get("/model-cards/claude-3-5-sonnet")
    assert response.status_code == 200
    data = response.json()
    assert data["is_small_variant"] is False
    # Sonnet is large, so terseify (small_only) should not apply
    terseify = next((r for r in data["rules"] if r["name"] == "terseify_if_small"), None)
    assert terseify is not None
    assert terseify["will_apply"] is False


def test_get_model_card_anthropic_applies_xml_wrap() -> None:
    response = client.get("/model-cards/claude-3-5-sonnet")
    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "anthropic"
    # Anthropic family should have xml_wrap rule
    xml_wrap = next((r for r in data["rules"] if r["name"] == "xml_wrap_sections"), None)
    assert xml_wrap is not None
    assert xml_wrap["will_apply"] is True


def test_get_model_card_openai_does_not_apply_xml_wrap() -> None:
    response = client.get("/model-cards/gpt-4o")
    assert response.status_code == 200
    data = response.json()
    assert data["family"] == "openai"
    # OpenAI family should not have xml_wrap rule
    xml_wrap = next((r for r in data["rules"] if r["name"] == "xml_wrap_sections"), None)
    assert xml_wrap is None


def test_get_model_card_requires_no_auth() -> None:
    # Like /trace-format/schema, this is public reference material
    response = client.get("/model-cards/claude-3-5-sonnet")
    assert response.status_code == 200
    # No Authorization header needed, no cookies


def test_get_model_card_reasoning_model_flags_true_and_shows_thinking() -> None:
    response = client.get("/model-cards/claude-sonnet-4-5")
    assert response.status_code == 200
    data = response.json()
    assert data["supports_reasoning"] is True
    assert "thinking=" in data["code_sample"]


def test_get_model_card_non_reasoning_model_flags_false_and_omits_thinking() -> None:
    response = client.get("/model-cards/gpt-4o")
    assert response.status_code == 200
    data = response.json()
    assert data["supports_reasoning"] is False
    assert '"type": "enabled"' not in data["code_sample"]
    assert "# thinking= / reasoning_effort= omitted" in data["code_sample"]


def test_get_model_card_code_sample_uses_the_actual_model_string() -> None:
    response = client.get("/model-cards/gpt-4o-mini")
    assert response.status_code == 200
    data = response.json()
    assert '"gpt-4o-mini"' in data["code_sample"]
    # reprompt_core is this project's own internal package - the sample
    # must be directly usable by an external caller (pip install litellm),
    # not reference a package only Reprompt's own codebase has installed.
    assert "import litellm" in data["code_sample"]
    assert "reprompt_core" not in data["code_sample"]
