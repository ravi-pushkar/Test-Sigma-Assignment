"""Integration coverage for indexing the pinned PR against a Gitea checkout."""

from pathlib import Path
import subprocess

import pytest

from blast_agent.code_index.indexer import index_pr
from blast_agent.code_index.pr_diff import PR_META
from blast_agent.contracts import CodeSymbol, PullRequestChange
from blast_agent.crawl import ArtifactStore


PROJECT_ROOT = Path(__file__).parents[2]
REPO_DIR = PROJECT_ROOT / "third_party" / "gitea"
DIFF_FIXTURE = Path(__file__).parents[1] / "fixtures" / "diffs" / "pr-37045.diff"


def _base_revision_available() -> bool:
    if not (REPO_DIR / ".git").exists():
        return False
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_DIR),
                "show",
                "--quiet",
                str(PR_META["base_sha"]),
            ],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


pytestmark = pytest.mark.skipif(
    not _base_revision_available(), reason="pinned Gitea base revision is unavailable"
)


def test_index_pr_live_records_and_ids_are_stable(tmp_path: Path) -> None:
    diff_text = DIFF_FIXTURE.read_text(encoding="utf-8")
    store = ArtifactStore(tmp_path)

    summary = index_pr(REPO_DIR, diff_text, "live-index", store)
    assert summary["code_symbols"] >= 15

    symbol_paths = sorted((tmp_path / "records" / "code_symbols").glob("*.json"))
    change_paths = sorted((tmp_path / "records" / "pr_changes").glob("*.json"))
    symbols = [
        CodeSymbol.model_validate_json(path.read_text(encoding="utf-8"))
        for path in symbol_paths
    ]
    changes = [
        PullRequestChange.model_validate_json(path.read_text(encoding="utf-8"))
        for path in change_paths
    ]

    issue_new_names = {
        symbol.qualified_name
        for symbol in symbols
        if symbol.file == "routers/web/repo/issue_new.go"
    }
    assert {"NewIssue", "ValidateRepoMetasForNewIssue"} <= issue_new_names

    issue_meta_names = {
        symbol.qualified_name
        for symbol in symbols
        if symbol.file == "routers/web/repo/issue_page_meta.go"
    }
    assert {
        "retrieveRepoIssueMetaData",
        "IssuePageMetaData.retrieveAssigneesData",
    } <= issue_meta_names

    template = next(
        symbol
        for symbol in symbols
        if symbol.kind == "template"
        and symbol.file == "templates/repo/issue/new_form.tmpl"
    )
    assert "locale:repo.issues.create" in template.ui_anchors
    assert "text:Create Issue" in template.ui_anchors

    indexed_suffixes = {".go", ".tmpl", ".ts"}
    assert all(
        change.changed_symbol_ids or Path(change.file).suffix not in indexed_suffixes
        for change in changes
    )

    first_symbol_ids = [symbol.id for symbol in symbols]
    first_change_ids = [change.id for change in changes]
    index_pr(REPO_DIR, diff_text, "live-index-second", store)
    second_symbols = [
        CodeSymbol.model_validate_json(path.read_text(encoding="utf-8"))
        for path in symbol_paths
    ]
    second_changes = [
        PullRequestChange.model_validate_json(path.read_text(encoding="utf-8"))
        for path in change_paths
    ]
    assert [symbol.id for symbol in second_symbols] == first_symbol_ids
    assert [change.id for change in second_changes] == first_change_ids
