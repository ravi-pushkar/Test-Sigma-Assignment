"""Read repository files at immutable Git revisions."""

from functools import lru_cache
from pathlib import Path
import subprocess


@lru_cache(maxsize=None)
def file_at(repo_dir: Path, sha: str, path: str) -> str | None:
    """Return ``path`` at ``sha``, or ``None`` when Git cannot read it."""

    result = subprocess.run(
        ["git", "-C", str(repo_dir), "show", f"{sha}:{path}"],
        capture_output=True,
        check=False,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


__all__ = ["file_at"]
