"""Tests for reprompt_core.llm.json_extract.extract_json.

Cases mirror the real prompted-JSON quirks observed against NVIDIA NIM's
Nemotron (markdown fences, preamble, a stray trailing brace) plus the
must-not-break case of already-clean native-JSON-mode output.
"""

from __future__ import annotations

import json

from reprompt_core.llm.json_extract import extract_json


def _roundtrips(raw: str) -> object:
    """extract_json(raw) must produce a string json.loads can parse."""
    return json.loads(extract_json(raw))


def test_clean_object_passes_through() -> None:
    assert _roundtrips('{"variants": ["a", "b"]}') == {"variants": ["a", "b"]}


def test_strips_markdown_json_fence() -> None:
    assert _roundtrips('```json\n{"variants": ["a"]}\n```') == {"variants": ["a"]}


def test_strips_plain_fence() -> None:
    assert _roundtrips('```\n{"x": 1}\n```') == {"x": 1}


def test_ignores_preamble_before_json() -> None:
    raw = 'Sure! Here are the variants:\n```json\n{"variants": ["x"]}\n```'
    assert _roundtrips(raw) == {"variants": ["x"]}


def test_drops_trailing_extra_brace() -> None:
    # The exact judge failure: one extra closing brace after valid JSON.
    raw = '{"criteria": [{"name": "accuracy", "score": 1.0}]}}'
    assert _roundtrips(raw) == {"criteria": [{"name": "accuracy", "score": 1.0}]}


def test_drops_trailing_prose() -> None:
    raw = '{"ok": true}\n\nHope that helps!'
    assert _roundtrips(raw) == {"ok": True}


def test_braces_inside_string_values_are_respected() -> None:
    # A {{placeholder}} inside a string must not throw off brace matching.
    raw = '{"variants": ["keep {{var}} intact"]}'
    assert _roundtrips(raw) == {"variants": ["keep {{var}} intact"]}


def test_array_root() -> None:
    assert _roundtrips("[1, 2, 3]") == [1, 2, 3]


def test_escaped_quote_inside_string() -> None:
    raw = '{"reasoning": "the candidate \\"Paris\\" is correct"}'
    assert _roundtrips(raw) == {"reasoning": 'the candidate "Paris" is correct'}


def test_no_json_returns_stripped_input() -> None:
    # Nothing JSON-looking: hand back stripped input so the caller's own
    # parse-error path fires exactly as before.
    assert extract_json("  no json here  ") == "no json here"


def test_empty_and_none() -> None:
    assert extract_json("") == ""
    assert extract_json(None) == ""
