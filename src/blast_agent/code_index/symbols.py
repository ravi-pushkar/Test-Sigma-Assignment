"""Pure-text heuristics for finding changed symbols in supported source files.

This module deliberately does not parse Go, Go templates, or TypeScript.  Its
regular-expression heuristics are small, deterministic, and intended to give
pull-request indexing useful symbol-sized spans without language toolchains.
"""

from __future__ import annotations

from bisect import bisect_right
from pathlib import PurePosixPath
import re
from typing import Literal, TypeAlias

from blast_agent.contracts import CodeSymbol, stable_id

from .pr_diff import PR_META, FileDiff, Hunk


SymbolKind: TypeAlias = Literal[
    "function", "method", "type", "template", "template_block", "ts_module"
]
SymbolTuple: TypeAlias = tuple[str, SymbolKind, int, int]

_GO_SYMBOL_RE = re.compile(
    r"^func (?:\(\s*\w+\s+\*?(\w+)\s*\) )?(\w+)\(|^type (\w+) ",
    re.MULTILINE,
)
_GO_DECL_RE = re.compile(r"^(?:func|type|var|const)\b", re.MULTILINE)
_TEMPLATE_DEFINE_RE = re.compile(r'\{\{\s*define\s+"([^"]+)"\s*\}\}')
_TS_SYMBOL_RE = re.compile(
    r"^(?:export )?(?:async )?function (\w+)"
    r"|^(?:export )?const (\w+) = (?:async )?\(",
    re.MULTILINE,
)


def _line_number(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _line_count(content: str) -> int:
    return max(1, len(content.splitlines()))


def _span_end(start_line: int, declaration_lines: list[int], eof: int) -> int:
    next_index = bisect_right(declaration_lines, start_line)
    return declaration_lines[next_index] - 1 if next_index < len(declaration_lines) else eof


def extract_go_symbols(content: str) -> list[SymbolTuple]:
    """Extract top-level Go functions, methods, and types."""

    eof = _line_count(content)
    declaration_lines = [
        _line_number(content, match.start()) for match in _GO_DECL_RE.finditer(content)
    ]
    symbols: list[SymbolTuple] = []
    for match in _GO_SYMBOL_RE.finditer(content):
        start = _line_number(content, match.start())
        receiver, function_name, type_name = match.groups()
        if type_name is not None:
            qualified_name = type_name
            kind: SymbolKind = "type"
        elif receiver is not None:
            qualified_name = f"{receiver}.{function_name}"
            kind = "method"
        else:
            qualified_name = function_name
            kind = "function"
        symbols.append(
            (qualified_name, kind, start, _span_end(start, declaration_lines, eof))
        )
    return symbols


def extract_template_symbols(content: str, path: str) -> list[SymbolTuple]:
    """Extract a whole-template symbol and named ``define`` blocks."""

    eof = _line_count(content)
    qualified_name = path.removeprefix("templates/").removesuffix(".tmpl")
    symbols: list[SymbolTuple] = [(qualified_name, "template", 1, eof)]
    definitions = list(_TEMPLATE_DEFINE_RE.finditer(content))
    for index, match in enumerate(definitions):
        start = _line_number(content, match.start())
        end = (
            _line_number(content, definitions[index + 1].start()) - 1
            if index + 1 < len(definitions)
            else eof
        )
        symbols.append((match.group(1), "template_block", start, end))
    return symbols


def extract_ts_symbols(content: str, path: str) -> list[SymbolTuple]:
    """Extract a TypeScript module and top-level function declarations."""

    eof = _line_count(content)
    matches = list(_TS_SYMBOL_RE.finditer(content))
    start_lines = [_line_number(content, match.start()) for match in matches]
    symbols: list[SymbolTuple] = [(path, "ts_module", 1, eof)]
    for index, (match, start) in enumerate(zip(matches, start_lines, strict=True)):
        end = start_lines[index + 1] - 1 if index + 1 < len(start_lines) else eof
        symbols.append((match.group(1) or match.group(2), "function", start, end))
    return symbols


def symbols_for_file(path: str, content: str) -> list[SymbolTuple]:
    """Dispatch symbol extraction based on the file suffix."""

    suffix = PurePosixPath(path).suffix
    if suffix == ".go":
        return extract_go_symbols(content)
    if suffix == ".tmpl":
        return extract_template_symbols(content, path)
    if suffix == ".ts":
        return extract_ts_symbols(content, path)
    return []


def _intersects(start: int, end: int, hunk: Hunk, side: Literal["old", "new"]) -> bool:
    range_start = hunk.old_start if side == "old" else hunk.new_start
    count = hunk.old_count if side == "old" else hunk.new_count
    range_end = range_start + max(count, 1) - 1
    return start <= range_end and range_start <= end


def _records_for_side(
    file_diff: FileDiff,
    content: str | None,
    run_id: str,
    repo_sha: str,
    side: Literal["old", "new"],
) -> list[CodeSymbol]:
    if content is None:
        return []
    return [
        CodeSymbol(
            id=stable_id("symbol", repo_sha, file_diff.path, qualified_name),
            run_id=run_id,
            source="code_index",
            source_revision=repo_sha,
            repo_sha=repo_sha,
            file=file_diff.path,
            qualified_name=qualified_name,
            kind=kind,
            line_start=start,
            line_end=end,
            ui_anchors=[],
        )
        for qualified_name, kind, start, end in symbols_for_file(file_diff.path, content)
        if any(_intersects(start, end, hunk, side) for hunk in file_diff.hunks)
    ]


def changed_symbols(
    file_diff: FileDiff,
    base_content: str | None,
    head_content: str | None,
    run_id: str,
) -> list[CodeSymbol]:
    """Build symbols intersecting the changed line ranges of ``file_diff``."""

    if file_diff.change_type == "added":
        return _records_for_side(
            file_diff, head_content, run_id, str(PR_META["head_sha"]), "new"
        )
    if file_diff.change_type not in {"modified", "deleted"}:
        return []

    records = _records_for_side(
        file_diff, base_content, run_id, str(PR_META["base_sha"]), "old"
    )
    if file_diff.change_type == "modified":
        known_names = {record.qualified_name for record in records}
        head_records = _records_for_side(
            file_diff, head_content, run_id, str(PR_META["head_sha"]), "new"
        )
        records.extend(
            record for record in head_records if record.qualified_name not in known_names
        )
    return records


__all__ = [
    "changed_symbols",
    "extract_go_symbols",
    "extract_template_symbols",
    "extract_ts_symbols",
    "symbols_for_file",
]
