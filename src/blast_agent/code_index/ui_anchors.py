"""Mine deterministic UI anchors from source-symbol spans."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from blast_agent.contracts import CodeSymbol

from .repository import file_at


_LOCALE_RE = re.compile(r'Locale\.TrN?\s+"([\w.-]+)"')
_HREF_RE = re.compile(r'href="(/[^"]*)"')
_ID_RE = re.compile(r'id="([^"]+)"')
_ROUTE_RE = re.compile(r'\bm\.(?:Get|Post|Combo)\(\s*"([^"]+)"')
_TPL_NAME_RE = re.compile(r'\btemplates\.TplName\s*=\s*"([^"]+)"')
_TPL_CONST_RE = re.compile(r'\btpl\w*\b[^=\n]*=\s*"([^"]+)"')
_QUERY_SELECTOR_RE = re.compile(
    r"querySelector(?:All)?\(\s*(['\"])([.#][^'\"]*)\1\s*\)"
)
_CSS_LITERAL_RE = re.compile(r"(['\"])([.#][^'\"\r\n]*)\1")


def _flatten_locale(value: Any, prefix: str, output: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_locale(nested, nested_prefix, output)
    elif isinstance(value, str) and prefix:
        output[prefix] = value


def load_locale(repo_dir: Path, sha: str) -> dict[str, str]:
    """Load and flatten Gitea's nested English locale at ``sha``."""

    content = file_at(repo_dir, sha, "options/locale/locale_en-US.json")
    if content is None:
        return {}
    try:
        raw = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {}
    flattened: dict[str, str] = {}
    _flatten_locale(raw, "", flattened)
    return flattened


def _append_unique(anchors: list[str], value: str) -> None:
    if value not in anchors and len(anchors) < 40:
        anchors.append(value)


def anchors_for_symbol(
    symbol: CodeSymbol, content: str, locale: dict[str, str]
) -> list[str]:
    """Return UI anchors found inside a symbol's inclusive line span."""

    lines = content.splitlines()
    span = "\n".join(lines[max(0, symbol.line_start - 1) : symbol.line_end])
    anchors: list[str] = []

    if symbol.file.endswith(".tmpl"):
        for match in _LOCALE_RE.finditer(span):
            key = match.group(1)
            _append_unique(anchors, f"locale:{key}")
            if key in locale:
                _append_unique(anchors, f"text:{locale[key]}")
        for match in _HREF_RE.finditer(span):
            href = match.group(1)
            if "{{" not in href:
                _append_unique(anchors, f"href:{href}")
        for match in _ID_RE.finditer(span):
            _append_unique(anchors, f"css:#{match.group(1)}")
        _append_unique(anchors, f"template:{symbol.file}")

    if symbol.file.endswith(".go") and symbol.file.startswith("routers/"):
        for match in _ROUTE_RE.finditer(span):
            _append_unique(anchors, f"route:{match.group(1)}")
        for pattern in (_TPL_NAME_RE, _TPL_CONST_RE):
            for match in pattern.finditer(span):
                _append_unique(anchors, f"template_name:{match.group(1)}")

    if symbol.file.endswith(".ts"):
        for match in _QUERY_SELECTOR_RE.finditer(span):
            _append_unique(anchors, f"css:{match.group(2)}")
        for match in _CSS_LITERAL_RE.finditer(span):
            _append_unique(anchors, f"css:{match.group(2)}")

    return anchors[:40]


def attach_anchors(
    symbols: list[CodeSymbol],
    file_contents: dict[str, str],
    locale: dict[str, str],
) -> list[CodeSymbol]:
    """Fill anchors on symbols whose source content is available."""

    for symbol in symbols:
        content = file_contents.get(symbol.file)
        if content is not None:
            symbol.ui_anchors = anchors_for_symbol(symbol, content, locale)
    return symbols


__all__ = ["anchors_for_symbol", "attach_anchors", "load_locale"]
