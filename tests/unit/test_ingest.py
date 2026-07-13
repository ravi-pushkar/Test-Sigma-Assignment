"""Unit coverage for deterministic documentation ingestion."""

from pathlib import Path
from typing import Any

from blast_agent.contracts import Requirement
from blast_agent.crawl import ArtifactStore
from blast_agent.ingest import (
    CachedLLM,
    DocSegment,
    extract_article_text,
    extract_requirements,
    ingest_docs,
    restore_docs_snapshots,
    segment,
)


FIXTURE = Path("tests/fixtures/docs/issues-prs_labels.html")
URI = "https://docs.gitea.com/1.27/usage/issues-prs/labels"


def test_missing_docs_snapshots_are_restored_from_fixtures(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    docs_dir = tmp_path / "data/raw/docs"

    assert restore_docs_snapshots(docs_dir) is True
    assert sorted(path.name for path in docs_dir.glob("*.html")) == [
        "issues-prs_automatically-linked-references.html",
        "issues-prs_issue-pull-request-templates.html",
        "issues-prs_labels.html",
    ]


class FakeGemini:
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def generate_json(
        self, prompt: str, response_schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((prompt, response_schema))
        return {"requirements": []}


def _slice_without_headings(article_text: str, item: DocSegment) -> str:
    lines = article_text[item.start_offset : item.end_offset].splitlines()
    return "\n".join(
        line
        for line in lines
        if not line.startswith(("H1:", "H2:", "H3:", "H4:"))
    )


def test_extract_and_segment_real_snapshot() -> None:
    article_text = extract_article_text(FIXTURE.read_text(encoding="utf-8"))
    segments = segment(URI, article_text)

    assert segments
    assert (
        segments[0].heading_path[0] == "Labels"
        or "Labels" in segments[0].heading_path
    )
    for item in segments:
        assert _slice_without_headings(article_text, item) == item.text


def test_segmentation_is_deterministic() -> None:
    html = FIXTURE.read_text(encoding="utf-8")

    first_text = extract_article_text(html)
    second_text = extract_article_text(html)
    assert first_text == second_text
    assert segment(URI, first_text) == segment(URI, second_text)


def test_cached_llm_calls_through_then_reuses_cache(tmp_path: Path) -> None:
    client = FakeGemini()
    llm = CachedLLM(client, tmp_path)
    schema = {"type": "OBJECT"}

    assert llm.generate("first", schema) == {"requirements": []}
    assert len(client.calls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1

    assert llm.generate("first", schema) == {"requirements": []}
    assert len(client.calls) == 1

    assert llm.generate("second", schema) == {"requirements": []}
    assert len(client.calls) == 2
    assert len(list(tmp_path.glob("*.json"))) == 2

    reloaded = CachedLLM(client, tmp_path)
    assert reloaded.generate("first", schema) == {"requirements": []}
    assert len(client.calls) == 2


class RequirementLLM:
    def generate(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "requirements": [
                {
                    "statement": "repository owner can create a label",
                    "actor": "repository owner",
                    "action": "create",
                    "object": "a label",
                    "acceptance_clues": ["New Label"],
                    "source_quote": "Repository owners can create labels.",
                },
                {
                    "statement": "user can launch a rocket",
                    "actor": "user",
                    "action": "launch",
                    "object": "a rocket",
                    "acceptance_clues": ["Launch"],
                    "source_quote": "A rocket launch button is available.",
                },
            ]
        }


def test_extract_requirements_rejects_unquoted_items_and_stabilizes_id() -> None:
    item = DocSegment(
        uri=URI,
        heading_path=["Labels", "Creating Labels"],
        text="Repository owners can create labels. Select New Label to begin.",
        start_offset=10,
        end_offset=75,
    )

    records, rejects = extract_requirements(
        [item], RequirementLLM(), "run-one", "revision"
    )
    repeated, _ = extract_requirements(
        [item], RequirementLLM(), "run-two", "revision"
    )

    assert len(records) == 1
    assert len(rejects) == 1
    assert rejects[0]["reason"] == "quote-not-found"
    assert isinstance(records[0], Requirement)
    Requirement.model_validate(records[0].model_dump())
    assert records[0].id == repeated[0].id


class PromptQuoteLLM:
    def generate(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "requirements": [
                {
                    "statement": "user can create an issue",
                    "actor": "user",
                    "action": "create",
                    "object": "an issue",
                    "acceptance_clues": ["New Issue"],
                    "source_quote": "Users can create an issue.",
                }
            ]
        }


def test_ingest_docs_persists_requirements(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.html"
    snapshot.write_text(
        "<article><h1>Issues</h1><p>Users can create an issue.</p></article>",
        encoding="utf-8",
    )
    store = ArtifactStore(tmp_path / "run")

    counts = ingest_docs(
        [(snapshot, URI)], PromptQuoteLLM(), "run-one", "revision", store
    )

    assert counts == {"segments": 1, "requirements": 1, "rejects": 0}
    paths = list((tmp_path / "run/records/requirements").glob("*.json"))
    assert len(paths) == 1
