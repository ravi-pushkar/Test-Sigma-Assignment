"""Round-trip and identity tests for the shared contract models."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from blast_agent.contracts import (
    AbsenceObservation,
    CodeSymbol,
    ImpactFinding,
    Interaction,
    PullRequestChange,
    Requirement,
    ScreenState,
    TraceLink,
    UIElement,
    UserFlow,
    stable_id,
)


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "contracts"

FIXTURES = [
    ("screen_state.json", ScreenState),
    ("ui_element.json", UIElement),
    ("interaction.json", Interaction),
    ("user_flow.json", UserFlow),
    ("requirement.json", Requirement),
    ("code_symbol.json", CodeSymbol),
    ("pull_request_change.json", PullRequestChange),
    ("trace_link.json", TraceLink),
    ("absence_observation.json", AbsenceObservation),
    ("impact_finding.json", ImpactFinding),
]


@pytest.mark.parametrize(("fixture_name", "model_type"), FIXTURES)
def test_contract_fixture_round_trip(fixture_name: str, model_type: type[Any]) -> None:
    fixture_json = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")

    record = model_type.model_validate_json(fixture_json)
    round_tripped = model_type.model_validate_json(record.model_dump_json())

    assert round_tripped == record


def test_contract_rejects_unknown_and_missing_fields() -> None:
    data = json.loads((FIXTURE_DIR / "screen_state.json").read_text(encoding="utf-8"))

    with pytest.raises(ValidationError):
        ScreenState.model_validate({**data, "unknown_field": "not allowed"})

    data.pop("url")
    with pytest.raises(ValidationError):
        ScreenState.model_validate(data)


def test_stable_id_is_deterministic() -> None:
    first = stable_id("screen", " HTTP://LOCALHOST:3000/demo/demo-repo/issues ", "HASH")
    second = stable_id("screen", "http://localhost:3000/demo/demo-repo/issues", "hash")

    assert first == second
    assert first != stable_id(
        "screen", "http://localhost:3000/demo/demo-repo/issues", "different-hash"
    )


def natural_id(fixture_name: str, data: dict[str, Any]) -> str:
    """Recompute the documented natural ID for one concrete fixture."""

    if fixture_name == "screen_state.json":
        return stable_id("screen", data["url"], data["visible_text_hash"])
    if fixture_name == "ui_element.json":
        return stable_id("element", data["screen_id"], data["role"], data["name"])
    if fixture_name == "interaction.json":
        return stable_id(
            "interaction",
            data["source_state_id"],
            data["element_id"],
            data["action"],
            data["target_state_id"],
        )
    if fixture_name == "user_flow.json":
        return stable_id("flow", data["goal"], data["start_state_id"], data["end_state_id"])
    if fixture_name == "requirement.json":
        return stable_id("requirement", data["source_span"]["uri"], data["statement"])
    if fixture_name == "code_symbol.json":
        return stable_id("symbol", data["repo_sha"], data["file"], data["qualified_name"])
    if fixture_name == "pull_request_change.json":
        return stable_id("pr_change", str(data["pr_number"]), data["file"])
    if fixture_name == "trace_link.json":
        return stable_id(
            "trace_link",
            data["source_entity_id"],
            data["target_entity_id"],
            data["link_type"],
        )
    if fixture_name == "absence_observation.json":
        return stable_id("absence", data["requirement_id"], data["crawl_run_id"])
    if fixture_name == "impact_finding.json":
        return stable_id(
            "impact", data["changed_symbol_id"], str(sorted(data["affected_entity_ids"]))
        )
    raise AssertionError(f"No natural key configured for {fixture_name}")


@pytest.mark.parametrize("fixture_name", [name for name, _ in FIXTURES])
def test_fixture_id_matches_natural_key(fixture_name: str) -> None:
    data = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))

    assert data["id"] == natural_id(fixture_name, data)
