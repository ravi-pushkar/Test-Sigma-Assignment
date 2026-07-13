"""Unit coverage for deterministic golden-set evaluation."""

from __future__ import annotations

import json
from pathlib import Path

from blast_agent.evals.metrics import (
    absence_metrics,
    impact_metrics,
    link_metrics,
    requirement_recall,
)
from blast_agent.evals.runner import evaluate
from blast_agent.evals.stability import jaccard, pairwise_stability


URI = "https://docs.example.test/issues"


def _base(record_id: str, run_id: str = "crawl") -> dict:
    return {
        "id": record_id,
        "schema_version": "1.0.0",
        "run_id": run_id,
        "source": "unit-test",
        "source_revision": "revision",
    }


def _screen(record_id: str = "screen:new", route: str = "/issues/new") -> dict:
    return {
        **_base(record_id),
        "url": f"https://example.test{route}",
        "route_pattern": route,
        "title": "Issues",
        "dom_artifact": "dom/screen.html",
        "screenshot_artifact": "screenshots/screen.png",
        "visible_text_hash": record_id,
    }


def _element(name: str = "Create Issue", screen_id: str = "screen:new") -> dict:
    return {
        **_base(f"element:{name.casefold().replace(' ', '-')}"),
        "screen_id": screen_id,
        "role": "button",
        "name": name,
        "locator_evidence": {"role": "button"},
        "attributes": {},
        "bounds": None,
    }


def _symbol(file: str = "templates/new.tmpl") -> dict:
    return {
        **_base(f"symbol:{file}", "code"),
        "repo_sha": "revision",
        "file": file,
        "qualified_name": f"{file}:root",
        "kind": "template",
        "line_start": 1,
        "line_end": 2,
        "ui_anchors": [],
    }


def _link(element_id: str, symbol_id: str) -> dict:
    return {
        **_base(f"link:{element_id}:{symbol_id}"),
        "source_entity_id": element_id,
        "target_entity_id": symbol_id,
        "link_type": "rendered_by",
        "confidence": 0.8,
        "method": "unit",
        "evidence": ["exact"],
        "review_status": "auto_accepted",
    }


def _requirement(record_id: str = "requirement:create", text: str = "Create issue") -> dict:
    return {
        **_base(record_id, "docs"),
        "statement": text,
        "actor": "user",
        "action": "create",
        "object": "issue",
        "acceptance_clues": ["issue form"],
        "source_span": {"uri": URI, "heading_path": [], "quote": text},
        "testable": True,
    }


def _flow() -> dict:
    return {
        **_base("flow:create"),
        "goal": "Create an issue",
        "interaction_ids": [],
        "start_state_id": "screen:new",
        "end_state_id": "screen:new",
        "discovery_source": "manual",
    }


def _impact(affected: list[str] | None = None) -> dict:
    return {
        **_base("impact:one"),
        "changed_symbol_id": "symbol:templates/new.tmpl",
        "path_entity_ids": [],
        "affected_entity_ids": (
            affected
            if affected is not None
            else ["element:create-issue", "flow:create"]
        ),
        "severity": "high",
        "confidence": 0.9,
        "summary": "templates/new.tmpl",
    }


def _absence() -> dict:
    return {
        **_base("absence:create"),
        "requirement_id": "requirement:create",
        "crawl_run_id": "crawl",
        "search_scope": "/issues",
        "expected_evidence": ["issue form"],
        "confidence": 0.9,
        "explanation": "not rendered",
    }


def _gold() -> dict:
    return {
        "requirements": {
            "must_extract": [
                {
                    "id": "gold:create",
                    "source_uri": URI,
                    "keywords": ["creat", "issue"],
                }
            ],
            "expected_absent_in_crawl": [{"gold_id": "gold:create"}],
        },
        "links": {
            "must_link": [
                {
                    "element_name": "Create Issue",
                    "route": "/issues/new",
                    "symbol_file": "templates/new.tmpl",
                }
            ],
            "must_not_link": [],
        },
        "impacts": {
            "required_affected_routes": ["/issues/new"],
            "required_affected_flow_goal_keywords": [["create", "issue"]],
            "required_unmapped_files": ["styles/unmapped.css"],
            "min_findings": 1,
        },
        "thresholds": {
            "requirement_recall_min": 1.0,
            "link_must_precision": 1.0,
            "link_recall_min": 1.0,
            "impact_required_recall": 1.0,
            "stability_jaccard_min": 0.9,
        },
    }


def _write_records(root: Path, kind: str, records: list[dict]) -> None:
    directory = root / "records" / kind
    directory.mkdir(parents=True, exist_ok=True)
    for index, record in enumerate(records):
        (directory / f"{index}.json").write_text(json.dumps(record), encoding="utf-8")


def test_requirement_recall_full_and_partial() -> None:
    gold = _gold()
    full = requirement_recall([_requirement()], gold)
    assert full == {
        "recall": 1.0,
        "recalled_ids": ["gold:create"],
        "missed_ids": [],
        "extracted_total": 1,
    }

    partial_gold = _gold()
    partial_gold["requirements"]["must_extract"].append(
        {"id": "gold:labels", "source_uri": URI, "keywords": ["label"]}
    )
    partial = requirement_recall([_requirement()], partial_gold)
    assert partial["recall"] == 0.5
    assert partial["missed_ids"] == ["gold:labels"]


def test_link_recall_and_must_not_violation() -> None:
    element = _element()
    symbol = _symbol()
    gold = _gold()
    gold["links"]["must_not_link"] = list(gold["links"]["must_link"])
    result = link_metrics(
        [_link(element["id"], symbol["id"])], [element], [_screen()], [symbol], gold
    )
    assert result["recall"] == 1.0
    assert result["matched"] == gold["links"]["must_link"]
    assert result["violations"] == gold["links"]["must_not_link"]


def test_impact_metrics_all_required_and_missing_route() -> None:
    lookups = {"elements": [_element()], "screens": [_screen()], "flows": [_flow()]}
    complete = impact_metrics([_impact()], ["styles/unmapped.css"], lookups, _gold())
    assert complete["overall_pass"] is True
    assert complete["findings_count"] == 1

    missing_gold = _gold()
    missing_gold["impacts"]["required_affected_routes"].append("/issues/{number}")
    missing = impact_metrics([_impact()], ["styles/unmapped.css"], lookups, missing_gold)
    assert missing["required_routes"]["/issues/{number}"] is False
    assert missing["overall_pass"] is False


def test_absence_found_and_missing() -> None:
    found = absence_metrics([_absence()], [_requirement()], _gold())
    assert found == {"expected": 1, "found": 1, "missing": []}
    missing = absence_metrics([], [_requirement()], _gold())
    assert missing == {"expected": 1, "found": 0, "missing": ["gold:create"]}


def test_jaccard_edges() -> None:
    assert jaccard(set(), set()) == 1.0
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0


def test_pairwise_stability_detects_differing_screen(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_records(first, "screens", [_screen(route="/one")])
    _write_records(second, "screens", [_screen(route="/two")])

    result = pairwise_stability([first, second])
    assert result["screens"] == 0.0
    assert result["elements"] == 1.0


def test_evaluate_good_then_forbidden_link_violation(tmp_path: Path) -> None:
    crawl = tmp_path / "crawl"
    code = tmp_path / "code"
    docs = tmp_path / "docs"
    gold_path = tmp_path / "gold.json"
    element = _element()
    symbol = _symbol()

    _write_records(crawl, "screens", [_screen()])
    _write_records(crawl, "elements", [element])
    _write_records(crawl, "flows", [_flow()])
    _write_records(crawl, "trace_links", [_link(element["id"], symbol["id"])])
    _write_records(crawl, "impacts", [_impact()])
    _write_records(crawl, "absences", [_absence()])
    _write_records(code, "code_symbols", [symbol])
    change = {
        **_base("change:css", "code"),
        "pr_number": 1,
        "title": "Change CSS",
        "base_sha": "base",
        "head_sha": "head",
        "merge_commit_sha": None,
        "file": "styles/unmapped.css",
        "change_type": "modified",
        "patch": "diff",
        "changed_symbol_ids": [],
    }
    _write_records(code, "pr_changes", [change])
    _write_records(docs, "requirements", [_requirement()])
    gold = _gold()
    gold_path.write_text(json.dumps(gold), encoding="utf-8")

    good = evaluate(crawl, code, docs, gold_path, [])
    assert good["overall_pass"] is True
    assert good["checks"]["stability"]["status"] == "skipped"

    gold["links"]["must_not_link"] = list(gold["links"]["must_link"])
    gold_path.write_text(json.dumps(gold), encoding="utf-8")
    bad = evaluate(crawl, code, docs, gold_path, [])
    assert bad["overall_pass"] is False
    assert bad["checks"]["link_must_precision"]["status"] == "failed"
