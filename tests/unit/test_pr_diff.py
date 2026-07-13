"""Tests for pull-request diff acquisition data and parsing."""

from collections import Counter
from pathlib import Path

import pytest

from blast_agent.code_index.pr_diff import (
    build_pr_changes,
    parse_diff,
    restore_diff_snapshot,
    snapshot_diff,
)
from blast_agent.contracts import PullRequestChange, stable_id


DIFF_FIXTURE = Path(__file__).parents[1] / "fixtures" / "diffs" / "pr-37045.diff"


def test_parse_real_pr_diff() -> None:
    file_diffs = parse_diff(DIFF_FIXTURE.read_text(encoding="utf-8"))

    assert len(file_diffs) == 21
    by_path = {file_diff.path: file_diff for file_diff in file_diffs}
    assert by_path["templates/repo/issue/new_form.tmpl"].change_type == "modified"
    assert (
        by_path["web_src/js/features/repo-issue-sidebar-combolist.test.ts"].change_type
        == "added"
    )

    deletion_only = by_path["models/issues/issue_project.go"]
    added_lines = [
        line
        for line in deletion_only.patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    assert added_lines == []

    assert all(
        file_diff.hunks or file_diff.change_type == "renamed" for file_diff in file_diffs
    )
    assert Counter(file_diff.change_type for file_diff in file_diffs) == {
        "added": 1,
        "modified": 20,
    }


def test_missing_diff_is_restored_from_fixture(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    destination = tmp_path / "data/raw/code/pr-37045.diff"

    assert restore_diff_snapshot(destination) is True
    assert destination.is_file()
    assert len(parse_diff(destination.read_text(encoding="utf-8"))) == 21


def test_build_pr_changes_are_valid_and_stable() -> None:
    diff_text = DIFF_FIXTURE.read_text(encoding="utf-8")

    first = build_pr_changes(diff_text, "run-1")
    second = build_pr_changes(diff_text, "run-2")

    assert len(first) == 21
    assert all(isinstance(change, PullRequestChange) for change in first)
    assert [change.id for change in first] == [change.id for change in second]
    assert all(
        change.id == stable_id("pr_change", "37045", change.file) for change in first
    )


def test_parse_deleted_renamed_and_omitted_hunk_counts() -> None:
    diff_text = """diff --git a/removed.txt b/removed.txt
deleted file mode 100644
index 1234567..0000000
--- a/removed.txt
+++ /dev/null
@@ -3 +3,2 @@
-gone
+replacement one
+replacement two
diff --git a/old-name.txt b/new-name.txt
similarity index 100%
rename from old-name.txt
rename to new-name.txt
"""

    deleted, renamed = parse_diff(diff_text)

    assert deleted.path == "removed.txt"
    assert deleted.old_path is None
    assert deleted.change_type == "deleted"
    assert len(deleted.hunks) == 1
    assert deleted.hunks[0].old_start == 3
    assert deleted.hunks[0].old_count == 1
    assert deleted.hunks[0].new_start == 3
    assert deleted.hunks[0].new_count == 2
    assert renamed.path == "new-name.txt"
    assert renamed.old_path == "old-name.txt"
    assert renamed.change_type == "renamed"
    assert renamed.hunks == []


def test_snapshot_diff_is_immutable(tmp_path: Path) -> None:
    destination = tmp_path / "snapshot.diff"

    snapshot_diff("same content\n", destination)
    snapshot_diff("same content\n", destination)
    assert destination.read_bytes() == b"same content\n"

    with pytest.raises(ValueError, match="immutable diff snapshot"):
        snapshot_diff("different content\n", destination)
