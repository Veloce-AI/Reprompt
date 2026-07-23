"""Tests for reprompt_api.system_models — operator-configured
REPROMPT_RUBRIC_MODEL/REPROMPT_JUDGE_MODEL/REPROMPT_MUTATOR_MODEL env var
overrides. See DEV_TRACKER.md's "System model config" entry.
"""

from __future__ import annotations

import pytest

from reprompt_api.system_models import system_model_env_var_name, system_model_override


def test_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPROMPT_JUDGE_MODEL", raising=False)
    assert system_model_override("judge") is None


def test_returns_none_when_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPROMPT_JUDGE_MODEL", "   ")
    assert system_model_override("judge") is None


def test_returns_the_configured_model_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPROMPT_JUDGE_MODEL", "nvidia_nim/deepseek-ai/deepseek-v4-flash")
    assert system_model_override("judge") == "nvidia_nim/deepseek-ai/deepseek-v4-flash"


def test_each_purpose_reads_its_own_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPROMPT_RUBRIC_MODEL", "model-a")
    monkeypatch.setenv("REPROMPT_JUDGE_MODEL", "model-b")
    monkeypatch.setenv("REPROMPT_MUTATOR_MODEL", "model-c")

    assert system_model_override("rubric_generation") == "model-a"
    assert system_model_override("judge") == "model-b"
    assert system_model_override("mutator") == "model-c"


def test_env_var_name_mapping() -> None:
    assert system_model_env_var_name("rubric_generation") == "REPROMPT_RUBRIC_MODEL"
    assert system_model_env_var_name("judge") == "REPROMPT_JUDGE_MODEL"
    assert system_model_env_var_name("mutator") == "REPROMPT_MUTATOR_MODEL"
