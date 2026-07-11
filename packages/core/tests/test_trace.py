import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from refract_core.trace import TraceFileError, load_trace_file, parse_trace_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "filename",
    ["sequential_5stage.json", "parallel_2branch.json", "mixed_12stage.json"],
)
def test_fixture_parses_cleanly(filename: str) -> None:
    trace_file = load_trace_file(FIXTURES_DIR / filename)
    assert trace_file.pipeline.stages
    assert trace_file.traces
    for trace in trace_file.traces:
        assert trace.records


def test_sequential_fixture_is_a_straight_chain() -> None:
    trace_file = load_trace_file(FIXTURES_DIR / "sequential_5stage.json")
    stages = trace_file.pipeline.stages
    assert len(stages) == 5
    assert stages[0].depends_on == []
    for stage in stages[1:]:
        assert len(stage.depends_on) == 1


def test_parallel_fixture_has_a_stage_with_two_dependents() -> None:
    trace_file = load_trace_file(FIXTURES_DIR / "parallel_2branch.json")
    dependency_counts: dict[str, int] = {}
    for stage in trace_file.pipeline.stages:
        for dep in stage.depends_on:
            dependency_counts[dep] = dependency_counts.get(dep, 0) + 1
    assert any(count >= 2 for count in dependency_counts.values())


def test_mixed_fixture_uses_multiple_models() -> None:
    trace_file = load_trace_file(FIXTURES_DIR / "mixed_12stage.json")
    assert len(trace_file.pipeline.stages) == 12
    models = {stage.model for stage in trace_file.pipeline.stages}
    assert len(models) >= 2


def test_missing_required_field_is_field_level() -> None:
    data = json.loads((FIXTURES_DIR / "sequential_5stage.json").read_text())
    del data["pipeline"]["stages"][0]["prompt_template"]

    with pytest.raises(TraceFileError) as exc_info:
        parse_trace_file(data)

    message = str(exc_info.value)
    assert "prompt_template" in message
    assert "pipeline" in message and "stages" in message


def test_wrong_type_is_field_level() -> None:
    data = json.loads((FIXTURES_DIR / "sequential_5stage.json").read_text())
    data["traces"][0]["records"][0]["latency_ms"] = "not-a-number"

    with pytest.raises(TraceFileError) as exc_info:
        parse_trace_file(data)

    message = str(exc_info.value)
    assert "latency_ms" in message


def test_unknown_depends_on_id_is_rejected() -> None:
    data = json.loads((FIXTURES_DIR / "sequential_5stage.json").read_text())
    data["pipeline"]["stages"][1]["depends_on"] = ["does_not_exist"]

    with pytest.raises(TraceFileError) as exc_info:
        parse_trace_file(data)

    message = str(exc_info.value)
    assert "does_not_exist" in message


def test_stage_record_referencing_unknown_stage_is_rejected() -> None:
    data = json.loads((FIXTURES_DIR / "sequential_5stage.json").read_text())
    data["traces"][0]["records"][0]["stage_id"] = "no_such_stage"

    with pytest.raises(TraceFileError) as exc_info:
        parse_trace_file(data)

    message = str(exc_info.value)
    assert "no_such_stage" in message


def test_duplicate_stage_ids_are_rejected() -> None:
    data = json.loads((FIXTURES_DIR / "sequential_5stage.json").read_text())
    data["pipeline"]["stages"][1]["id"] = data["pipeline"]["stages"][0]["id"]

    with pytest.raises(TraceFileError) as exc_info:
        parse_trace_file(data)

    assert "duplicate stage id" in str(exc_info.value)


def test_malformed_json_gives_a_clear_error(tmp_path: Path) -> None:
    bad_file = tmp_path / "broken.json"
    bad_file.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(TraceFileError) as exc_info:
        load_trace_file(bad_file)

    assert "not valid JSON" in str(exc_info.value)


def test_bare_minimum_stage_record_validates_cleanly() -> None:
    """schema_version 1.1: tokens, latency_ms, cost, and documents are all
    optional on a StageRecord — a trace source that doesn't capture per-call
    accounting must still validate cleanly, with sane empty/None defaults.
    """
    data = {
        "pipeline": {
            "id": "minimal-pipeline",
            "name": "Minimal Pipeline",
            "stages": [
                {
                    "id": "only_stage",
                    "name": "Only Stage",
                    "model": "gpt-4o-mini",
                    "prompt_template": "Say hello to {{name}}.",
                }
            ],
        },
        "traces": [
            {
                "trace_id": "trace-0",
                "query": {"name": "world"},
                "records": [
                    {
                        "stage_id": "only_stage",
                        "rendered_prompt": "Say hello to world.",
                        "output": "Hello, world!",
                    }
                ],
            }
        ],
    }

    trace_file = parse_trace_file(data)

    assert trace_file.schema_version == "1.1"
    record = trace_file.traces[0].records[0]
    assert record.tokens is None
    assert record.latency_ms is None
    assert record.cost is None
    assert record.documents == []
    assert record.metadata == {}

    stage = trace_file.pipeline.stages[0]
    assert stage.system_prompt is None
    assert stage.metadata == {}
    assert trace_file.traces[0].metadata == {}


def test_format_pydantic_error_never_raised_directly() -> None:
    # parse_trace_file must always wrap Pydantic's ValidationError, never
    # let it escape raw - that's the whole point of TraceFileError.
    with pytest.raises(TraceFileError):
        try:
            parse_trace_file({})
        except ValidationError:
            pytest.fail("parse_trace_file leaked a raw pydantic.ValidationError")
