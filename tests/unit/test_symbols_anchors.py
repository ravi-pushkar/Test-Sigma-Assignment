"""Unit tests for text-only symbol extraction and UI-anchor mining."""

from blast_agent.code_index.pr_diff import FileDiff, Hunk, PR_META
from blast_agent.code_index.symbols import (
    changed_symbols,
    extract_go_symbols,
    extract_template_symbols,
    extract_ts_symbols,
)
from blast_agent.code_index.ui_anchors import anchors_for_symbol
from blast_agent.contracts import CodeSymbol, stable_id


def _symbol(
    file: str,
    qualified_name: str,
    kind: str,
    line_start: int,
    line_end: int,
) -> CodeSymbol:
    sha = str(PR_META["base_sha"])
    return CodeSymbol(
        id=stable_id("symbol", sha, file, qualified_name),
        run_id="unit",
        source="code_index",
        source_revision=sha,
        repo_sha=sha,
        file=file,
        qualified_name=qualified_name,
        kind=kind,
        line_start=line_start,
        line_end=line_end,
        ui_anchors=[],
    )


def test_extract_go_symbols_and_changed_span_intersection() -> None:
    content = """type Widget struct {
}
func Build() {
}
func (w *Widget) Save() {
}
"""

    assert extract_go_symbols(content) == [
        ("Widget", "type", 1, 2),
        ("Build", "function", 3, 4),
        ("Widget.Save", "method", 5, 6),
    ]

    file_diff = FileDiff(
        path="widgets.go",
        old_path=None,
        change_type="modified",
        hunks=[Hunk(old_start=6, old_count=1, new_start=6, new_count=1)],
        patch="",
    )
    symbols = changed_symbols(file_diff, content, content, "unit")
    assert [(symbol.qualified_name, symbol.kind) for symbol in symbols] == [
        ("Widget.Save", "method")
    ]


def test_template_definitions_and_anchors() -> None:
    content = """{{define "first"}}
<a id="new-issue" href="/repo/issues/new">{{ctx.Locale.Tr "repo.issues.create"}}</a>
{{end}}
{{define "second"}}
<a href="{{AppSubUrl}}/settings">Settings</a>
{{end}}
"""
    path = "templates/repo/issue/new_form.tmpl"

    assert extract_template_symbols(content, path) == [
        ("repo/issue/new_form", "template", 1, 6),
        ("first", "template_block", 1, 3),
        ("second", "template_block", 4, 6),
    ]

    symbol = _symbol(path, "first", "template_block", 1, 3)
    assert anchors_for_symbol(
        symbol, content, {"repo.issues.create": "Create Issue"}
    ) == [
        "locale:repo.issues.create",
        "text:Create Issue",
        "href:/repo/issues/new",
        "css:#new-issue",
        f"template:{path}",
    ]


def test_ts_functions_and_query_selector_anchor() -> None:
    content = """export async function load() {
  return document.querySelector('#issue');
}
export const find = () => {
  return document.querySelectorAll('.item');
};
"""
    path = "web_src/js/issues.ts"

    assert extract_ts_symbols(content, path) == [
        (path, "ts_module", 1, 6),
        ("load", "function", 1, 3),
        ("find", "function", 4, 6),
    ]
    symbol = _symbol(path, "find", "function", 4, 6)
    assert anchors_for_symbol(symbol, content, {}) == ["css:.item"]


def test_changed_symbols_for_added_file_uses_head_revision() -> None:
    content = """export function added() {
  return true;
}
"""
    file_diff = FileDiff(
        path="web_src/js/added.ts",
        old_path=None,
        change_type="added",
        hunks=[Hunk(old_start=0, old_count=0, new_start=1, new_count=3)],
        patch="",
    )

    symbols = changed_symbols(file_diff, None, content, "unit")
    assert {symbol.qualified_name for symbol in symbols} == {
        "web_src/js/added.ts",
        "added",
    }
    assert all(symbol.repo_sha == PR_META["head_sha"] for symbol in symbols)


def test_changed_symbols_includes_modified_file_head_only_symbol() -> None:
    base = """func Existing() {
}
"""
    head = """func Existing() {
}
func Added() {
}
"""
    file_diff = FileDiff(
        path="changed.go",
        old_path=None,
        change_type="modified",
        hunks=[Hunk(old_start=2, old_count=0, new_start=3, new_count=2)],
        patch="",
    )

    symbols = changed_symbols(file_diff, base, head, "unit")
    by_name = {symbol.qualified_name: symbol for symbol in symbols}
    assert set(by_name) == {"Existing", "Added"}
    assert by_name["Existing"].repo_sha == PR_META["base_sha"]
    assert by_name["Added"].repo_sha == PR_META["head_sha"]
