"""Source-code indexing and pull-request diff utilities."""

from .pr_diff import (
    PR_META,
    FileDiff,
    Hunk,
    acquire_diff,
    build_pr_changes,
    parse_diff,
    restore_diff_snapshot,
    snapshot_diff,
)
from .indexer import index_pr
from .repository import file_at
from .symbols import (
    changed_symbols,
    extract_go_symbols,
    extract_template_symbols,
    extract_ts_symbols,
    symbols_for_file,
)
from .ui_anchors import anchors_for_symbol, attach_anchors, load_locale

__all__ = [
    "PR_META",
    "FileDiff",
    "Hunk",
    "acquire_diff",
    "build_pr_changes",
    "parse_diff",
    "restore_diff_snapshot",
    "snapshot_diff",
    "anchors_for_symbol",
    "attach_anchors",
    "changed_symbols",
    "extract_go_symbols",
    "extract_template_symbols",
    "extract_ts_symbols",
    "file_at",
    "index_pr",
    "load_locale",
    "symbols_for_file",
]
