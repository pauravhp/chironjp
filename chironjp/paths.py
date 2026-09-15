"""Generic filesystem and executable helpers with no machine-specific roots."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def real(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def is_within(path: Path, root: Path) -> bool:
    try:
        real(path).relative_to(real(root))
        return True
    except ValueError:
        return False


def require_within(
    path: str | os.PathLike[str], root: str | os.PathLike[str], label: str,
) -> Path:
    resolved = real(path)
    allowed = real(root)
    if not is_within(resolved, allowed):
        raise ValueError(f"{label} escapes configured root: {resolved}")
    return resolved


def private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def private_file(path: Path) -> None:
    path.chmod(0o600)


def discover_executable(
    name: str,
    *,
    explicit: str | os.PathLike[str] | None = None,
    env_var: str | None = None,
) -> Path | None:
    """Resolve an explicit, environment, or PATH executable in that order."""
    candidate = explicit or (os.environ.get(env_var) if env_var else None)
    if candidate:
        path = real(candidate)
        return path if path.is_file() and os.access(path, os.X_OK) else None
    located = shutil.which(name)
    return real(located) if located else None
