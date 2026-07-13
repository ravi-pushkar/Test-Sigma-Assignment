"""Filesystem persistence for crawler artifacts and contract records."""

from __future__ import annotations

from pathlib import Path

from blast_agent.contracts import ContractRecord, UIElement

from .extractor import ExtractedScreen


def _file_id(record_id: str) -> str:
    return record_id.replace(":", "_")


class ArtifactStore:
    """Persist crawl output beneath a single run root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def save_screen(self, extracted: ExtractedScreen) -> None:
        file_id = _file_id(extracted.screen.id)
        dom_path = self.root / "dom" / f"{file_id}.html"
        screenshot_path = self.root / "screenshots" / f"{file_id}.png"
        dom_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        dom_path.write_text(extracted.html, encoding="utf-8")
        screenshot_path.write_bytes(extracted.screenshot_png)
        self.save_record(extracted.screen, "screens")

    def save_elements(self, elements: list[UIElement]) -> None:
        for element in elements:
            self.save_record(element, "elements")

    def save_record(self, record: ContractRecord, kind_dir: str | Path) -> None:
        kind_path = Path(kind_dir)
        if kind_path.is_absolute() or ".." in kind_path.parts:
            raise ValueError("kind_dir must remain within the records directory")
        record_path = self.root / "records" / kind_path / f"{_file_id(record.id)}.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def manifest(self) -> dict[str, object]:
        records_root = self.root / "records"
        counts: dict[str, int] = {}
        if records_root.is_dir():
            for kind_dir in sorted(path for path in records_root.iterdir() if path.is_dir()):
                counts[kind_dir.name] = sum(
                    1 for path in kind_dir.glob("*.json") if path.is_file()
                )
        return {"records": counts, "root": str(self.root)}


__all__ = ["ArtifactStore"]
