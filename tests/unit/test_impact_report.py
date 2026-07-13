"""Unit coverage for deterministic impact aggregation and rendering."""

from blast_agent.code_index.pr_diff import PR_META
from blast_agent.contracts import stable_id
from blast_agent.reasoning import build_findings, render_report


def _row(**overrides) -> dict:
    row = {
        "change_id": "change:one",
        "file": "templates/repo/issue/new_form.tmpl",
        "change_type": "modified",
        "symbol_id": "symbol:one",
        "element_id": "element:create",
        "element_name": "Create Issue",
        "screen_id": "screen:new",
        "screen_route": "/{owner}/{repo}/issues/new",
        "flow_id": None,
        "flow_goal": None,
        "flow_step_count": 0,
        "requirement_id": None,
        "requirement_statement": None,
        "mapping_confidence": 0.75,
        "path_confidence": 0.75,
    }
    row.update(overrides)
    return row


def test_build_findings_applies_severity_and_confidence_rules() -> None:
    rows = [
        _row(
            symbol_id="symbol:high",
            flow_id="flow:create",
            flow_goal="Create an issue",
            flow_step_count=3,
            mapping_confidence=0.91,
            path_confidence=0.64,
            requirement_id="requirement:create",
        ),
        _row(
            symbol_id="symbol:medium",
            element_id="element:label",
            flow_id="flow:labels",
            mapping_confidence=0.79,
            path_confidence=0.79,
        ),
        _row(
            symbol_id="symbol:low",
            element_id=None,
            screen_id="screen:issues",
            screen_route="/{owner}/{repo}/issues/{number}",
            mapping_confidence=0.88,
            path_confidence=0.88,
        ),
        _row(
            symbol_id="symbol:none",
            element_id=None,
            screen_id=None,
            mapping_confidence=None,
            path_confidence=None,
        ),
    ]

    findings = build_findings(rows, "run-test", "revision-test")
    by_symbol = {finding.changed_symbol_id: finding for finding in findings}

    assert set(by_symbol) == {"symbol:high", "symbol:medium", "symbol:low"}
    assert by_symbol["symbol:high"].severity == "high"
    assert by_symbol["symbol:high"].confidence == 0.91
    assert by_symbol["symbol:medium"].severity == "medium"
    assert by_symbol["symbol:low"].severity == "low"
    assert by_symbol["symbol:high"].path_entity_ids == [
        ["change:one", "symbol:high", "element:create", "screen:new", "flow:create"]
    ]


def test_impact_id_is_stable_when_row_order_changes() -> None:
    rows = [
        _row(flow_id="flow:create", mapping_confidence=0.9),
        _row(element_id="element:title", flow_id=None, mapping_confidence=0.8),
    ]
    first = build_findings(rows, "run-a", "revision")[0]
    second = build_findings(list(reversed(rows)), "run-b", "revision")[0]

    expected = stable_id(
        "impact", first.changed_symbol_id, str(sorted(first.affected_entity_ids))
    )
    assert first.id == second.id == expected


def test_render_report_uses_human_labels_and_explicit_uncertainty() -> None:
    finding = build_findings(
        [
            _row(
                symbol_id="symbol:high",
                flow_id="flow:create",
                flow_goal="Create an issue",
                flow_step_count=3,
                mapping_confidence=0.92,
            )
        ],
        "run-report",
        "revision-report",
    )[0]
    report = render_report(
        [finding],
        [
            {
                "file": "web_src/css/repo/issue.css",
                "change_type": "modified",
                "reason": "no symbols extracted",
            }
        ],
        {
            "pr": {
                **PR_META,
                "url": "https://github.com/go-gitea/gitea/pull/37045",
                "files_changed": 2,
            },
            "run_id": "run-report",
            "source_revision": "revision-report",
            "generated_at": "2026-07-11T12:00:00+00:00",
            "crawl_stats": {
                "screens": 4,
                "elements": 12,
                "flows": 2,
                "requirements": 0,
            },
            "entity_lookups": {
                "elements": {"element:create": "Create Issue"},
                "screens": {"screen:new": "/{owner}/{repo}/issues/new"},
                "flows": {
                    "flow:create": {
                        "goal": "  Create an issue.\n",
                        "step_count": 3,
                    }
                },
                "requirements": {},
            },
        },
    )

    assert PR_META["title"] in report
    assert (
        "Changes to templates/repo/issue/new_form.tmpl affect Create Issue "
        "across /{owner}/{repo}/issues/new."
    ) in report
    assert (
        "No requirements were ingested in this run; requirement-level coverage "
        "is not assessed."
    ) in report
    assert "## Not mapped to UI" in report
    assert "web_src/css/repo/issue.css" in report
    assert "- Create an issue. (3 steps)" in report
    assert "Create an issue.." not in report
    assert "Re-run:" not in report
    assert "{{" not in report
    assert "None" not in report


def test_render_report_deduplicates_labels_and_caps_evidence() -> None:
    rows = [
        _row(
            symbol_id="symbol:many",
            element_id=f"element:{index:02}",
            screen_id=(
                "screen:one" if index <= 4 else "screen:two" if index <= 6 else "screen:three"
            ),
            flow_id=None,
            mapping_confidence=0.8,
            path_confidence=0.8,
        )
        for index in range(1, 9)
    ]
    finding = build_findings(rows, "run-many", "revision-many")[0]
    element_names = {
        "element:01": "Notifications",
        "element:02": "Notifications",
        "element:03": "  Save\n   changes  ",
        "element:04": "X" * 45,
        "element:05": "Alpha",
        "element:06": "Beta",
        "element:07": "Gamma",
        "element:08": "Delta",
    }
    report = render_report(
        [finding],
        [],
        {
            "pr": {
                **PR_META,
                "url": "https://github.com/go-gitea/gitea/pull/37045",
                "files_changed": 1,
            },
            "run_id": "run-many",
            "source_revision": "revision-many",
            "generated_at": "2026-07-11T12:00:00+00:00",
            "crawl_stats": {
                "screens": 3,
                "elements": 8,
                "flows": 0,
                "requirements": 0,
            },
            "entity_lookups": {
                "elements": element_names,
                "screens": {
                    "screen:one": "/{owner}/{repo}/issues/new",
                    "screen:two": "/{owner}/{repo}/issues/new",
                    "screen:three": "/{owner}/{repo}/issues/{number}",
                },
                "flows": {},
                "requirements": {},
            },
        },
    )

    assert "Notifications (2 places)" in report
    assert "Save changes" in report
    assert f"{'X' * 39}…" in report
    assert "Gamma, and 1 more across" in report
    sentence = next(line for line in report.splitlines() if line.startswith("Changes to "))
    assert sentence.count("/{owner}/{repo}/issues/new") == 1
    assert sentence.count("/{owner}/{repo}/issues/{number}") == 1
    assert report.count("change:one → symbol:many → element:") == 5
    assert "… plus 3 more recorded paths (see impact records)." in report
