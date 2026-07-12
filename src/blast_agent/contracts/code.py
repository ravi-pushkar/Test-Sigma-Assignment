"""Contracts describing source code and pull request changes."""

from typing import Literal

from .common import ContractRecord


class CodeSymbol(ContractRecord):
    repo_sha: str
    file: str
    qualified_name: str
    kind: Literal[
        "function",
        "method",
        "type",
        "template",
        "template_block",
        "ts_module",
        "route",
    ]
    line_start: int
    line_end: int
    ui_anchors: list[str] = []


class PullRequestChange(ContractRecord):
    pr_number: int
    title: str
    base_sha: str
    head_sha: str
    merge_commit_sha: str | None
    file: str
    change_type: Literal["added", "modified", "deleted", "renamed"]
    patch: str
    changed_symbol_ids: list[str] = []
