"""Orchestrate pull-request code-symbol and UI-anchor indexing."""

from pathlib import Path

from blast_agent.contracts import CodeSymbol, PullRequestChange
from blast_agent.crawl import ArtifactStore

from .pr_diff import PR_META, build_pr_changes, parse_diff
from .repository import file_at
from .symbols import changed_symbols
from .ui_anchors import attach_anchors, load_locale


def index_pr(
    repo_dir: Path,
    diff_text: str,
    run_id: str,
    store: ArtifactStore,
) -> dict[str, int]:
    """Index changed symbols and PR-change records for one diff."""

    file_diffs = parse_diff(diff_text)
    symbols: list[CodeSymbol] = []
    file_contents: dict[str, str] = {}

    for file_diff in file_diffs:
        base_path = file_diff.old_path or file_diff.path
        base_content = file_at(repo_dir, str(PR_META["base_sha"]), base_path)
        head_content = file_at(repo_dir, str(PR_META["head_sha"]), file_diff.path)
        symbols.extend(
            changed_symbols(file_diff, base_content, head_content, run_id)
        )
        preferred_content = head_content if head_content is not None else base_content
        if preferred_content is not None:
            file_contents[file_diff.path] = preferred_content

    locale = load_locale(repo_dir, str(PR_META["base_sha"]))
    attach_anchors(symbols, file_contents, locale)

    symbol_ids_by_file: dict[str, list[str]] = {}
    for symbol in symbols:
        symbol_ids_by_file.setdefault(symbol.file, []).append(symbol.id)
        store.save_record(symbol, "code_symbols")

    changes: list[PullRequestChange] = build_pr_changes(diff_text, run_id)
    for change in changes:
        change.changed_symbol_ids = symbol_ids_by_file.get(change.file, [])
        store.save_record(change, "pr_changes")

    return {"code_symbols": len(symbols), "pr_changes": len(changes)}


__all__ = ["index_pr"]
