import subprocess

from app.config import BACKEND_DIR


def current_code_commit() -> str | None:
    """The checked-out commit, suffixed ``-dirty`` when the working tree has changes."""
    try:
        commit = _git("rev-parse", "HEAD")
        dirty = _git("status", "--porcelain")
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{commit}-dirty" if dirty else commit


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=BACKEND_DIR, capture_output=True, text=True, check=True
    ).stdout.strip()
