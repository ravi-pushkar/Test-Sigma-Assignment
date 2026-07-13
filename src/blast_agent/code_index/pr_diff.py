"""Acquire, parse, and snapshot unified pull-request diffs."""

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Literal

from blast_agent.contracts import PullRequestChange, stable_id


PR_META = {
    "pr_number": 37045,
    "title": "Refactor issue sidebar and fix various problems",
    "base_sha": "daf581fa892320f5d495b4073d6812b0ad8ddfc8",
    "head_sha": "e7095e0957a6b46273c2c21afff3450543cb8257",
    "merge_commit_sha": "6ca557371882871ab994b51df204942b45b5cf3b",
}

ChangeType = Literal["added", "modified", "deleted", "renamed"]

_SECTION_RE = re.compile(r"^diff --git ", re.MULTILINE)
_HUNK_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Hunk:
    """Line ranges declared by one unified-diff hunk header."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int


@dataclass(frozen=True)
class FileDiff:
    """The parsed metadata and verbatim patch for one changed file."""

    path: str
    old_path: str | None
    change_type: ChangeType
    hunks: list[Hunk]
    patch: str


def acquire_diff(repo_dir: Path, base: str, head: str) -> str:
    """Return the git diff between two revisions in ``repo_dir``."""

    result = subprocess.run(
        ["git", "-C", str(repo_dir), "diff", base, head],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout


def _marker_path(section: str, marker: str) -> str | None:
    match = re.search(rf"^{re.escape(marker)} (.+)$", section, re.MULTILINE)
    if match is None:
        return None
    path = match.group(1).split("\t", 1)[0]
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _metadata_path(section: str, label: str) -> str | None:
    match = re.search(rf"^{re.escape(label)} (.+)$", section, re.MULTILINE)
    return match.group(1) if match else None


def _header_paths(section: str) -> tuple[str, str]:
    first_line = section.splitlines()[0]
    match = re.match(r"diff --git a/(.+) b/(.+)$", first_line)
    if match is None:
        raise ValueError(f"Malformed diff header: {first_line!r}")
    return match.group(1), match.group(2)


def _parse_section(section: str) -> FileDiff:
    header_old, header_new = _header_paths(section)
    marker_old = _marker_path(section, "---")
    marker_new = _marker_path(section, "+++")
    rename_from = _metadata_path(section, "rename from")
    rename_to = _metadata_path(section, "rename to")

    if re.search(r"^new file mode ", section, re.MULTILINE):
        change_type: ChangeType = "added"
    elif re.search(r"^deleted file mode ", section, re.MULTILINE):
        change_type = "deleted"
    elif rename_from is not None:
        change_type = "renamed"
    else:
        change_type = "modified"

    if change_type == "renamed":
        path = rename_to or marker_new or header_new
        old_path = rename_from or marker_old or header_old
        if old_path == path:
            old_path = None
    elif change_type == "deleted":
        # A deletion's +++ marker is /dev/null, so retain the former path as
        # the record's file identity while reserving old_path for renames.
        path = marker_old or header_old
        old_path = None
    else:
        path = marker_new or header_new
        old_path = None

    hunks = [
        Hunk(
            old_start=int(match.group(1)),
            old_count=int(match.group(2) or 1),
            new_start=int(match.group(3)),
            new_count=int(match.group(4) or 1),
        )
        for match in _HUNK_RE.finditer(section)
    ]
    return FileDiff(
        path=path,
        old_path=old_path,
        change_type=change_type,
        hunks=hunks,
        patch=section,
    )


def parse_diff(diff_text: str) -> list[FileDiff]:
    """Parse a unified git diff into one :class:`FileDiff` per section."""

    starts = [match.start() for match in _SECTION_RE.finditer(diff_text)]
    return [
        _parse_section(diff_text[start:end])
        for start, end in zip(starts, [*starts[1:], len(diff_text)], strict=True)
    ]


def build_pr_changes(diff_text: str, run_id: str) -> list[PullRequestChange]:
    """Build validated contract records from a pull-request diff."""

    return [
        PullRequestChange(
            id=stable_id("pr_change", str(PR_META["pr_number"]), file_diff.path),
            run_id=run_id,
            source="code_index",
            source_revision=PR_META["base_sha"],
            pr_number=PR_META["pr_number"],
            title=PR_META["title"],
            base_sha=PR_META["base_sha"],
            head_sha=PR_META["head_sha"],
            merge_commit_sha=PR_META["merge_commit_sha"],
            file=file_diff.path,
            change_type=file_diff.change_type,
            patch=file_diff.patch,
            changed_symbol_ids=[],
        )
        for file_diff in parse_diff(diff_text)
    ]


def snapshot_diff(diff_text: str, dest: Path) -> None:
    """Create an immutable UTF-8 diff snapshot, accepting identical repeats."""

    content = diff_text.encode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("xb") as snapshot:
            snapshot.write(content)
    except FileExistsError:
        if dest.read_bytes() != content:
            raise ValueError(f"Refusing to replace immutable diff snapshot: {dest}") from None


def restore_diff_snapshot(diff_file: Path) -> bool:
    """Restore the committed PR diff fixture when ``diff_file`` is absent."""

    if diff_file.is_file():
        return False

    relative = Path("tests/fixtures/diffs/pr-37045.diff")
    fixture_path = Path.cwd() / relative
    if not fixture_path.is_file():
        fixture_path = Path(__file__).resolve().parents[3] / relative
    if not fixture_path.is_file():
        return False

    snapshot_diff(fixture_path.read_text(encoding="utf-8"), diff_file)
    return True
