"""Deterministic extraction and segmentation of documentation snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil


_BLOCK_TAGS = {"p", "li", "pre", "div"}
_DROPPED_TAGS = {"script", "style", "nav", "aside"}
_HEADING_RE = re.compile(r"^H([1-4]):\s*(.*)$")


@dataclass
class DocSegment:
    uri: str
    heading_path: list[str]
    text: str
    start_offset: int
    end_offset: int


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.in_article = False
        self.article_done = False
        self.article_depth = 0
        self.dropped_depth = 0
        self.heading_level: int | None = None
        self.heading_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.casefold()
        if self.article_done:
            return
        if tag == "article":
            if not self.in_article:
                self.in_article = True
                self.article_depth = 1
            else:
                self.article_depth += 1
            return
        if not self.in_article:
            return
        if self.dropped_depth:
            if tag in _DROPPED_TAGS:
                self.dropped_depth += 1
            return
        if tag in _DROPPED_TAGS:
            self.dropped_depth = 1
            return
        if tag in {"h1", "h2", "h3", "h4"}:
            self.heading_level = int(tag[1])
            self.heading_parts = []
            return
        if self.heading_level is None:
            self.parts.append(" ")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if self.in_article and not self.article_done and not self.dropped_depth:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if not self.in_article or self.article_done:
            return
        if self.dropped_depth:
            if tag in _DROPPED_TAGS:
                self.dropped_depth -= 1
            return
        if tag == "article":
            self.article_depth -= 1
            if self.article_depth == 0:
                self.in_article = False
                self.article_done = True
            return
        if self.heading_level is not None and tag == f"h{self.heading_level}":
            heading = _collapse_spaces("".join(self.heading_parts)).strip()
            self.parts.extend(("\n", f"H{self.heading_level}: {heading}", "\n"))
            self.heading_level = None
            self.heading_parts = []
            return
        if self.heading_level is None:
            self.parts.append("\n" if tag in _BLOCK_TAGS else " ")

    def handle_data(self, data: str) -> None:
        if not self.in_article or self.article_done or self.dropped_depth:
            return
        if self.heading_level is not None:
            self.heading_parts.append(data)
        else:
            self.parts.append(data)


def _collapse_spaces(value: str) -> str:
    # HTMLParser has already decoded character and entity references once.
    return re.sub(r"[^\S\n]+", " ", value)


def extract_article_text(html: str) -> str:
    """Extract normalized text from the first article in an HTML document."""

    parser = _ArticleParser()
    parser.feed(html)
    parser.close()
    text = _collapse_spaces("".join(parser.parts))
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def segment(uri: str, article_text: str) -> list[DocSegment]:
    """Split article text at headings once at least 200 body chars accumulate."""

    headings: list[str] = []
    current_path: list[str] = []
    body_ranges: list[tuple[int, int]] = []
    segments: list[DocSegment] = []

    def emit() -> None:
        nonlocal body_ranges, current_path
        if not body_ranges:
            return
        pieces = [article_text[start:end] for start, end in body_ranges]
        segments.append(
            DocSegment(
                uri=uri,
                heading_path=list(current_path),
                text="\n".join(pieces),
                start_offset=body_ranges[0][0],
                end_offset=body_ranges[-1][1],
            )
        )
        body_ranges = []

    offset = 0
    for line_with_ending in article_text.splitlines(keepends=True):
        line = line_with_ending.rstrip("\r\n")
        match = _HEADING_RE.fullmatch(line)
        if match:
            if body_ranges and sum(end - start for start, end in body_ranges) >= 200:
                emit()
            level = int(match.group(1))
            headings[level - 1 :] = [match.group(2).strip()]
            current_path = list(headings)
        elif line:
            body_ranges.append((offset, offset + len(line)))
        offset += len(line_with_ending)

    # splitlines(keepends=True) also handles the ordinary no-final-newline case.
    emit()
    return segments


def load_snapshot(path: Path, uri: str) -> list[DocSegment]:
    """Load one HTML snapshot and return its documentation segments."""

    html = Path(path).read_text(encoding="utf-8")
    return segment(uri, extract_article_text(html))
def restore_docs_snapshots(docs_dir: Path) -> bool:
    """Restore committed HTML snapshots when ``docs_dir`` has none."""

    if any(docs_dir.glob("*.html")):
        return False

    relative = Path("tests/fixtures/docs")
    fixture_dir = Path.cwd() / relative
    if not fixture_dir.is_dir():
        fixture_dir = Path(__file__).resolve().parents[3] / relative
    fixture_paths = sorted(fixture_dir.glob("*.html"))
    if not fixture_paths:
        return False

    docs_dir.mkdir(parents=True, exist_ok=True)
    for fixture_path in fixture_paths:
        shutil.copy2(fixture_path, docs_dir / fixture_path.name)
    return True

