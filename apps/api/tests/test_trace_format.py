"""Tests for GET /trace-format/schema."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from reprompt_api.main import app
from reprompt_api.trace_format import SCHEMA_PATH

client = TestClient(app)


def test_get_trace_format_schema_returns_committed_file_content() -> None:
    response = client.get("/trace-format/schema")
    assert response.status_code == 200
    assert response.json() == json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_get_trace_format_schema_requires_no_auth() -> None:
    # No Authorization header, no cookies - must still succeed (public
    # reference material, unlike every workspace-scoped endpoint).
    response = client.get("/trace-format/schema")
    assert response.status_code == 200
