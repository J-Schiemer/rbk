"""Workspace discovery: locate the active ``runbooks/`` directory."""

from __future__ import annotations

import os
from pathlib import Path

from rbk.runbook import RunbookError

RUNBOOK_SUBDIR = "runbooks"
ENV_VAR = "RBK_DIR"


def _runbooks_in(directory: Path) -> Path | None:
    candidate = directory / RUNBOOK_SUBDIR
    return candidate if candidate.is_dir() else None


def _workspace(path: Path, source: str) -> Path:
    resolved = path.resolve()
    if resolved.name == RUNBOOK_SUBDIR and resolved.is_dir():
        return resolved
    found = _runbooks_in(resolved)
    if found is None:
        raise RunbookError(f"{source} {resolved} has no {RUNBOOK_SUBDIR}/ directory")
    return found


def find_workspace(explicit: str | Path | None = None, *, start: Path | None = None) -> Path:
    """Return the runbooks directory: ``--dir`` > ``$RBK_DIR`` > upward discovery."""
    if explicit is not None:
        return _workspace(Path(explicit).expanduser(), "--dir")

    from_env = os.environ.get(ENV_VAR)
    if from_env:
        return _workspace(Path(from_env).expanduser(), f"${ENV_VAR}")

    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        found = _runbooks_in(directory)
        if found is not None:
            return found

    raise RunbookError(
        f"no {RUNBOOK_SUBDIR}/ directory found in {current} or any parent (use --dir or ${ENV_VAR})"
    )
