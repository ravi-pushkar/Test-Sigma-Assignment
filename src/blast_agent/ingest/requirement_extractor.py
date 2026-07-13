"""LLM-backed extraction of testable requirements from documentation."""

from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any

from blast_agent.contracts import Requirement, SourceSpan, stable_id
from blast_agent.crawl import ArtifactStore
from blast_agent.llm.gemini import GeminiClient, LLMUnavailable

from .loader import DocSegment, load_snapshot


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "requirements": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "statement": {"type": "STRING"},
                    "actor": {"type": "STRING"},
                    "action": {"type": "STRING"},
                    "object": {"type": "STRING"},
                    "acceptance_clues": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "source_quote": {"type": "STRING"},
                },
                "required": [
                    "statement",
                    "actor",
                    "action",
                    "object",
                    "acceptance_clues",
                    "source_quote",
                ],
            },
        }
    },
    "required": ["requirements"],
}

PROMPT_TEMPLATE = """Extract atomic, testable product requirements from this documentation segment.

Rules:
- Make each statement one sentence in actor-can-action-object form.
- actor must be the user role, such as "user", "repository owner", or "organization owner".
- acceptance_clues must contain exact UI words a tester would look for, such as button labels and menu names.
- source_quote MUST be a verbatim contiguous quote of at most 200 characters copied from the segment.
- Skip configuration or YAML reference material that has no user-visible behavior.
- Return an empty requirements list when nothing is testable.

URI: {uri}
Heading path: {heading_path}
Documentation segment:
{text}
"""


class CachedLLM:
    """Persist structured LLM responses by model, prompt, and schema."""

    def __init__(
        self,
        client: GeminiClient | None,
        cache_dir: Path = Path("data/cache/llm"),
    ) -> None:
        self.client = client
        self.cache_dir = Path(cache_dir)

    def generate(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.client.model if self.client else "none",
            "prompt": prompt,
            "schema": schema,
        }
        key = sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"{key}.json"
        if cache_path.is_file():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(cached, dict):
                raise ValueError(f"invalid cached LLM response: {cache_path}")
            return cached
        if self.client is None:
            raise LLMUnavailable(f"no Gemini client and cache miss for {key}")

        response = self.client.generate_json(prompt, schema)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.cache_dir,
            prefix=f".{key}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(response, temporary, sort_keys=True)
            temporary.write("\n")
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, cache_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return response


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def extract_requirements(
    segments: Iterable[DocSegment],
    llm: CachedLLM,
    run_id: str,
    source_revision: str,
) -> tuple[list[Requirement], list[dict]]:
    """Extract, validate, and deduplicate requirements from segments."""

    requirements: list[Requirement] = []
    rejects: list[dict] = []
    seen_ids: set[str] = set()
    for doc_segment in segments:
        prompt = PROMPT_TEMPLATE.format(
            uri=doc_segment.uri,
            heading_path=" > ".join(doc_segment.heading_path),
            text=doc_segment.text,
        )
        response = llm.generate(prompt, RESPONSE_SCHEMA)
        items = response.get("requirements", [])
        if not isinstance(items, list):
            raise ValueError("LLM response requirements must be a list")
        normalized_text = _normalized(doc_segment.text)
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("LLM requirement item must be an object")
            source_quote = str(item.get("source_quote", ""))
            if not _normalized(source_quote) or _normalized(source_quote) not in normalized_text:
                rejects.append(
                    {
                        "segment": list(doc_segment.heading_path),
                        "reason": "quote-not-found",
                        "item": item,
                    }
                )
                continue
            statement = str(item["statement"])
            requirement_id = stable_id(
                "requirement", doc_segment.uri, statement
            )
            if requirement_id in seen_ids:
                continue
            requirement = Requirement(
                id=requirement_id,
                run_id=run_id,
                source="ingest",
                source_revision=source_revision,
                statement=statement,
                actor=str(item["actor"]),
                action=str(item["action"]),
                object=str(item["object"]),
                acceptance_clues=[str(clue) for clue in item["acceptance_clues"]],
                testable=True,
                source_span=SourceSpan(
                    uri=doc_segment.uri,
                    heading_path=list(doc_segment.heading_path),
                    quote=source_quote,
                    start_offset=doc_segment.start_offset,
                    end_offset=doc_segment.end_offset,
                ),
            )
            seen_ids.add(requirement_id)
            requirements.append(requirement)
    return requirements, rejects


def ingest_docs(
    snapshot_paths: list[tuple[Path, str]],
    llm: CachedLLM,
    run_id: str,
    source_revision: str,
    store: ArtifactStore,
) -> dict[str, int]:
    """Ingest snapshots and persist their validated requirements."""

    segments = [
        doc_segment
        for path, uri in snapshot_paths
        for doc_segment in load_snapshot(path, uri)
    ]
    requirements, rejects = extract_requirements(
        segments, llm, run_id, source_revision
    )
    for requirement in requirements:
        store.save_record(requirement, "requirements")
    return {
        "segments": len(segments),
        "requirements": len(requirements),
        "rejects": len(rejects),
    }
