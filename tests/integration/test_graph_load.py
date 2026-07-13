"""Integration coverage for an idempotent Neo4j graph load."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path

from neo4j import GraphDatabase
import pytest

from blast_agent.contracts import (
    CodeSymbol,
    Interaction,
    PullRequestChange,
    Requirement,
    ScreenState,
    SourceSpan,
    TraceLink,
    UIElement,
    UserFlow,
)
from blast_agent.crawl import ArtifactStore
from blast_agent.graph import GraphWriter, record_absences, requirement_coverage


RUN_ID = "graph-it-run"
CODE_RUN_ID = "it-code-run"
PR_NUMBER = 990001
REVISION = "it-revision"


def _settings() -> tuple[str, str, str]:
    dotenv = GraphWriter._read_dotenv(Path(".env"))
    return (
        os.environ.get("NEO4J_URI")
        or dotenv.get("NEO4J_URI")
        or "bolt://localhost:7687",
        os.environ.get("NEO4J_USER") or dotenv.get("NEO4J_USER") or "neo4j",
        os.environ.get("NEO4J_PASSWORD")
        or dotenv.get("NEO4J_PASSWORD")
        or "password",
    )


def _neo4j_available() -> bool:
    uri, user, password = _settings()
    driver = None
    try:
        driver = GraphDatabase.driver(
            uri, auth=(user, password), connection_timeout=3.0
        )
        driver.verify_connectivity()
        return True
    except Exception:
        return False
    finally:
        if driver is not None:
            driver.close()


pytestmark = pytest.mark.skipif(
    not _neo4j_available(), reason="Neo4j is not reachable on bolt://localhost:7687"
)


def _base(record_id: str, run_id: str = RUN_ID) -> dict[str, object]:
    return {
        "id": record_id,
        "run_id": run_id,
        "source": "graph-integration-test",
        "source_revision": REVISION,
    }


def _clean_test_namespace(driver) -> None:
    with driver.session(database="neo4j") as session:
        session.run(
            "MATCH (n) "
            "WHERE n.run_id = $run_id OR n.id STARTS WITH 'it-' "
            "   OR (n:PullRequest AND n.number = $pr_number) "
            "   OR (n:CodeFile AND n.path STARTS WITH 'itfix/') "
            "DETACH DELETE n",
            run_id=RUN_ID,
            pr_number=PR_NUMBER,
        ).consume()


@pytest.fixture
def graph_driver():
    uri, user, password = _settings()
    driver = GraphDatabase.driver(
        uri, auth=(user, password), connection_timeout=3.0
    )
    _clean_test_namespace(driver)
    try:
        yield driver
    finally:
        _clean_test_namespace(driver)
        driver.close()


def _write_fixture(run_root: Path, code_root: Path) -> None:
    crawl_store = ArtifactStore(run_root)
    code_store = ArtifactStore(code_root)

    screens = [
        ScreenState(
            **_base("it-screen-list"),
            url="http://localhost/issues",
            route_pattern="/issues",
            title="Issues",
            dom_artifact="dom/it-screen-list.html",
            screenshot_artifact="screenshots/it-screen-list.png",
            visible_text_hash="it-hash-list",
        ),
        ScreenState(
            **_base("it-screen-form"),
            url="http://localhost/issues/new",
            route_pattern="/issues/new",
            title="New issue",
            dom_artifact="dom/it-screen-form.html",
            screenshot_artifact="screenshots/it-screen-form.png",
            visible_text_hash="it-hash-form",
        ),
    ]
    elements = [
        UIElement(
            **_base("it-element-new"),
            screen_id="it-screen-list",
            role="link",
            name="New Issue",
            locator_evidence={"text": "New Issue"},
            attributes={"href": "/issues/new"},
            bounds=(1.0, 2.0, 3.0, 4.0),
        ),
        UIElement(
            **_base("it-element-title"),
            screen_id="it-screen-form",
            role="textbox",
            name="Title",
            locator_evidence={"label": "Title"},
            attributes={"name": "title"},
            bounds=(5.0, 6.0, 7.0, 8.0),
        ),
    ]
    interaction = Interaction(
        **_base("it-interaction-open"),
        source_state_id="it-screen-list",
        target_state_id="it-screen-form",
        element_id="it-element-new",
        action="click",
        input_class=None,
        timestamp=datetime(2026, 7, 11, tzinfo=UTC),
        success=True,
    )
    flow = UserFlow(
        **_base("it-flow-new-issue"),
        goal="Open the new issue form",
        interaction_ids=[interaction.id],
        start_state_id=screens[0].id,
        end_state_id=screens[1].id,
        discovery_source="deterministic",
    )
    requirements = [
        Requirement(
            **_base("it-requirement-covered"),
            statement="Users can open the new issue form.",
            actor="user",
            action="open",
            object="new issue form",
            acceptance_clues=["A New Issue link is visible."],
            source_span=SourceSpan(
                uri="it://requirements/covered",
                quote="Users can open the new issue form.",
            ),
        ),
        Requirement(
            **_base("it-requirement-absent"),
            statement="Users can assign a milestone.",
            actor="user",
            action="assign",
            object="milestone",
            acceptance_clues=[],
            source_span=SourceSpan(
                uri="it://requirements/absent",
                quote="Users can assign a milestone.",
            ),
        ),
    ]
    for record in screens:
        crawl_store.save_record(record, "screens")
    for record in elements:
        crawl_store.save_record(record, "elements")
    crawl_store.save_record(interaction, "interactions")
    crawl_store.save_record(flow, "flows")
    for record in requirements:
        crawl_store.save_record(record, "requirements")

    symbols = [
        CodeSymbol(
            **_base("it-symbol-template", CODE_RUN_ID),
            repo_sha=REVISION,
            file="itfix/new_issue.py",
            qualified_name="itfix.new_issue.render",
            kind="function",
            line_start=1,
            line_end=5,
            ui_anchors=["New Issue"],
        ),
        CodeSymbol(
            **_base("it-symbol-handler", CODE_RUN_ID),
            repo_sha=REVISION,
            file="itfix/new_issue.py",
            qualified_name="itfix.new_issue.submit",
            kind="function",
            line_start=7,
            line_end=12,
            ui_anchors=["Title"],
        ),
    ]
    for symbol in symbols:
        code_store.save_record(symbol, "code_symbols")
    code_store.save_record(
        PullRequestChange(
            **_base("it-change-new-issue", CODE_RUN_ID),
            pr_number=PR_NUMBER,
            title="Integration graph fixture",
            base_sha="it-base-sha",
            head_sha="it-head-sha",
            merge_commit_sha=None,
            file="itfix/new_issue.py",
            change_type="modified",
            patch="@@ -1 +1 @@",
            changed_symbol_ids=[symbol.id for symbol in symbols],
        ),
        "pr_changes",
    )

    links = [
        TraceLink(
            **_base("it-link-implements"),
            source_entity_id="it-requirement-covered",
            target_entity_id="it-element-new",
            link_type="implements",
            confidence=0.95,
            method="integration-fixture",
            evidence=["New Issue link"],
            review_status="auto_accepted",
        ),
        TraceLink(
            **_base("it-link-rendered"),
            source_entity_id="it-element-new",
            target_entity_id="it-symbol-template",
            link_type="rendered_by",
            confidence=0.9,
            method="integration-fixture",
            evidence=["New Issue anchor"],
            review_status="auto_accepted",
        ),
    ]
    for link in links:
        crawl_store.save_record(link, "trace_links")


def test_graph_load_is_idempotent_and_reports_coverage(
    tmp_path: Path, graph_driver
) -> None:
    run_root = tmp_path / RUN_ID
    code_root = tmp_path / CODE_RUN_ID
    _write_fixture(run_root, code_root)
    observations = record_absences(run_root, RUN_ID, REVISION)
    assert [item.requirement_id for item in observations] == [
        "it-requirement-absent"
    ]

    writer = GraphWriter(graph_driver)
    writer.load_run(run_root, code_root)
    first_counts = writer.counts()
    assert first_counts["nodes"]["Screen"] >= 2
    assert first_counts["nodes"]["UIElement"] >= 2
    assert first_counts["nodes"]["CodeSymbol"] >= 2
    assert first_counts["relationships"]["IMPLEMENTED_BY"] >= 1

    writer.load_run(run_root, code_root)
    assert writer.counts() == first_counts

    coverage = {
        row["id"]: row for row in requirement_coverage(graph_driver, RUN_ID)
    }
    assert coverage["it-requirement-covered"]["covered"] is True
    assert coverage["it-requirement-covered"]["absent"] is False
    assert coverage["it-requirement-absent"]["covered"] is False
    assert coverage["it-requirement-absent"]["absent"] is True
