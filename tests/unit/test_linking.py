"""Unit tests for deterministic cross-layer candidate generation and scoring."""

from pathlib import Path

import pytest

from blast_agent.contracts import (
    CodeSymbol,
    Requirement,
    ScreenState,
    SourceSpan,
    TraceLink,
    UIElement,
    stable_id,
)
from blast_agent.crawl import ArtifactStore
from blast_agent.linking import (
    LinkCandidate,
    Signal,
    combined_confidence,
    link_run,
    requirement_ui_candidates,
    to_trace_links,
    ui_code_candidates,
)


REVISION = "daf581fa892320f5d495b4073d6812b0ad8ddfc8"
RUN_ID = "unit-linking"


def _element(
    name: str,
    *,
    href: str | None = None,
    css: str = "a.button",
) -> UIElement:
    attributes = {"href": href} if href is not None else {}
    return UIElement(
        id=stable_id("element", "screen:new-issue", "link", name),
        run_id=RUN_ID,
        source="test-crawler",
        source_revision=REVISION,
        screen_id="screen:new-issue",
        role="link",
        name=name,
        locator_evidence={"css": css},
        attributes=attributes,
        bounds=(0.0, 0.0, 100.0, 30.0),
    )


def _screen(route_pattern: str = "/{owner}/{repo}/issues/new") -> ScreenState:
    return ScreenState(
        id=stable_id("screen", "http://localhost/issues/new", "visible-hash"),
        run_id=RUN_ID,
        source="test-crawler",
        source_revision=REVISION,
        url="http://localhost/issues/new",
        route_pattern=route_pattern,
        title="New Issue",
        dom_artifact="dom/new-issue.html",
        screenshot_artifact="screenshots/new-issue.png",
        visible_text_hash="visible-hash",
    )


def _symbol(
    anchors: list[str],
    *,
    kind: str = "template",
    file: str = "templates/repo/issue/new_form.tmpl",
) -> CodeSymbol:
    qualified_name = f"{file}:symbol"
    return CodeSymbol(
        id=stable_id("symbol", REVISION, file, qualified_name),
        run_id="code-index",
        source="code_index",
        source_revision=REVISION,
        repo_sha=REVISION,
        file=file,
        qualified_name=qualified_name,
        kind=kind,
        line_start=1,
        line_end=10,
        ui_anchors=anchors,
    )


def _requirement(clues: list[str], object_: str = "new issue form") -> Requirement:
    statement = "Repository users can open the new issue form."
    return Requirement(
        id=stable_id("requirement", "requirements://unit", statement),
        run_id=RUN_ID,
        source="test-requirements",
        source_revision=REVISION,
        statement=statement,
        actor="repository user",
        action="open",
        object=object_,
        acceptance_clues=clues,
        source_span=SourceSpan(
            uri="requirements://unit",
            heading_path=["New issue"],
            quote=statement,
        ),
        testable=True,
    )


def test_text_anchor_creates_rendered_by_candidate_needing_review() -> None:
    element = _element("Create Issue")
    symbol = _symbol(["text:Create Issue"])

    candidates = ui_code_candidates([element], [], [symbol])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert (
        candidate.source_entity_id,
        candidate.target_entity_id,
        candidate.link_type,
    ) == (element.id, symbol.id, "rendered_by")
    links = to_trace_links(candidates, RUN_ID, REVISION)
    assert links[0].confidence == pytest.approx(0.65)
    assert links[0].review_status == "needs_review"


def test_text_and_href_signals_merge_and_auto_accept() -> None:
    href = "/demo/demo-repo/issues/new"
    element = _element("Create Issue", href=href)
    symbol = _symbol(["text:Create Issue", f"href:{href}"])

    candidates = ui_code_candidates([element], [], [symbol])

    assert len(candidates) == 1
    assert {signal.kind for signal in candidates[0].signals} == {
        "text-exact",
        "href-exact",
    }
    link = to_trace_links(candidates, RUN_ID, REVISION)[0]
    assert link.confidence == pytest.approx(1 - (0.35 * 0.3))
    assert link.review_status == "auto_accepted"


def test_identical_evidence_does_not_inflate_confidence() -> None:
    signals = [
        Signal("text-exact", "text:Create Issue", 0.65),
        Signal("href-exact", "text:Create Issue", 0.4),
    ]

    assert combined_confidence(signals) == pytest.approx(0.65)


def test_requirement_exact_clue_creates_implements_candidate() -> None:
    requirement = _requirement(["New Issue"])
    element = _element("New Issue")

    candidates = requirement_ui_candidates([requirement], [element], [])

    assert len(candidates) == 1
    assert candidates[0].link_type == "implements"
    assert candidates[0].source_entity_id == requirement.id
    assert candidates[0].target_entity_id == element.id
    link = to_trace_links(candidates, RUN_ID, REVISION)[0]
    assert link.confidence == pytest.approx(0.6)
    assert link.review_status == "needs_review"


def test_requirement_without_matching_evidence_emits_no_candidate() -> None:
    requirement = _requirement(["Submit Ticket"], object_="ticket submission form")

    assert requirement_ui_candidates([requirement], [_element("New Issue")], []) == []


def test_route_anchor_links_screen_to_handler() -> None:
    route = "/{owner}/{repo}/issues/new"
    screen = _screen(route)
    symbol = _symbol(
        [f"route:{route}"],
        kind="function",
        file="routers/web/repo/issue.go",
    )

    candidates = ui_code_candidates([], [screen], [symbol])

    assert len(candidates) == 1
    assert (
        candidates[0].source_entity_id,
        candidates[0].target_entity_id,
        candidates[0].link_type,
    ) == (screen.id, symbol.id, "handled_by")
    link = to_trace_links(candidates, RUN_ID, REVISION)[0]
    assert link.confidence == pytest.approx(0.75)
    assert link.review_status == "needs_review"


def test_trace_link_ids_are_stable_and_records_validate() -> None:
    candidate = LinkCandidate(
        "element:source",
        "symbol:target",
        "rendered_by",
        [Signal("text-exact", "text:Create Issue", 0.65)],
    )

    first = to_trace_links([candidate], RUN_ID, REVISION)[0]
    second = to_trace_links([candidate], RUN_ID, REVISION)[0]

    assert first.id == second.id == stable_id(
        "trace_link", "element:source", "symbol:target", "rendered_by"
    )
    assert TraceLink.model_validate(first.model_dump()) == first


def test_link_run_loads_records_and_writes_trace_links(tmp_path: Path) -> None:
    run_root = tmp_path / "crawl-run"
    code_root = tmp_path / "code-index"
    element = _element("Create Issue")
    screen = _screen()
    symbol = _symbol(["text:Create Issue"])
    crawl_store = ArtifactStore(run_root)
    crawl_store.save_record(element, "elements")
    crawl_store.save_record(screen, "screens")
    ArtifactStore(code_root).save_record(symbol, "code_symbols")

    counts = link_run(run_root, RUN_ID, code_root)

    assert counts == {
        "auto_accepted": 0,
        "needs_review": 1,
        "unresolved": 0,
    }
    paths = list((run_root / "records" / "trace_links").glob("*.json"))
    assert len(paths) == 1
    persisted = TraceLink.model_validate_json(paths[0].read_text(encoding="utf-8"))
    assert persisted.source_entity_id == element.id
    assert persisted.target_entity_id == symbol.id
    assert persisted.review_status == "needs_review"


def test_link_run_loads_requirements_from_separate_docs_root(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "crawl-run"
    docs_root = tmp_path / "docs-run"
    element = _element("New Issue")
    requirement = _requirement(["New Issue"])
    ArtifactStore(run_root).save_record(element, "elements")
    ArtifactStore(docs_root).save_record(requirement, "requirements")

    counts = link_run(run_root, RUN_ID, docs_run_root=docs_root)

    assert counts == {
        "auto_accepted": 0,
        "needs_review": 1,
        "unresolved": 0,
    }
    paths = list((run_root / "records" / "trace_links").glob("*.json"))
    assert len(paths) == 1
    persisted = TraceLink.model_validate_json(paths[0].read_text(encoding="utf-8"))
    assert persisted.link_type == "implements"
    assert persisted.source_entity_id == requirement.id
    assert persisted.target_entity_id == element.id
