"""Runbook YAML loading, validation, interpolation, and include resolution."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import yaml

RUNBOOK_KEYS = frozenset({"name", "description", "vars", "steps"})
STEP_KEYS = frozenset({"name", "run", "host", "include", "vars", "confirm"})
_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}")


class RunbookError(Exception):
    """Raised when a runbook is malformed or cannot be resolved."""


@dataclass(slots=True)
class Step:
    name: str
    run: str | None = None
    include: str | None = None
    host: str | None = None
    vars: dict[str, str] = field(default_factory=dict)
    confirm: bool = False


@dataclass(slots=True)
class Runbook:
    name: str
    description: str | None
    vars: dict[str, str]
    steps: list[Step]
    path: Path


class PlanStep(NamedTuple):
    name: str
    command: str
    host: str | None
    confirm: bool


def _reject_unknown_keys(data: Mapping, allowed: frozenset[str], where: str) -> None:
    unknown = {str(key) for key in data} - allowed
    if unknown:
        raise RunbookError(f"{where} has unknown key(s): {', '.join(sorted(unknown))}")


def _scalar_vars(value: object, where: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RunbookError(f"{where} must be a mapping")

    out: dict[str, str] = {}
    for key, val in value.items():
        if not isinstance(key, str) or not isinstance(val, (str, int, float, bool)):
            raise RunbookError(f"{where} entry {key!r} must be a string-keyed scalar")
        out[key] = str(val)
    return out


def _parse_step(raw: object, index: int, source: Path) -> Step:
    where = f"{source}: step {index + 1}"
    if not isinstance(raw, Mapping):
        raise RunbookError(f"{where} must be a mapping")
    _reject_unknown_keys(raw, STEP_KEYS, where)

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RunbookError(f"{where} requires a non-empty 'name'")

    run = raw.get("run")
    include = raw.get("include")
    if (run is None) == (include is None):
        raise RunbookError(f"{where} ({name!r}) must have exactly one of 'run' or 'include'")

    host = raw.get("host")
    for key, value in (("run", run), ("include", include), ("host", host)):
        if value is not None and not isinstance(value, str):
            raise RunbookError(f"{where} ({name!r}) '{key}' must be a string")

    confirm = raw.get("confirm", False)
    if not isinstance(confirm, bool):
        raise RunbookError(f"{where} ({name!r}) 'confirm' must be a boolean")

    return Step(
        name=name,
        run=run,
        include=include,
        host=host,
        vars=_scalar_vars(raw.get("vars"), f"{where} vars"),
        confirm=confirm,
    )


def load_runbook(path: str | Path) -> Runbook:
    """Read and validate a runbook file, raising ``RunbookError`` on any problem."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunbookError(f"cannot read runbook {path}: {exc.strerror or exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RunbookError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, Mapping):
        raise RunbookError(f"{path}: runbook must be a mapping")
    _reject_unknown_keys(data, RUNBOOK_KEYS, str(path))

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RunbookError(f"{path}: requires a non-empty 'name'")

    description = data.get("description")
    if description is not None and not isinstance(description, str):
        raise RunbookError(f"{path}: 'description' must be a string")

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raise RunbookError(f"{path}: 'steps' must be a list")

    return Runbook(
        name=name,
        description=description,
        vars=_scalar_vars(data.get("vars"), f"{path}: vars"),
        steps=[_parse_step(raw, index, path) for index, raw in enumerate(raw_steps)],
        path=path,
    )


def list_runbooks(runbooks_dir: str | Path) -> list[Runbook]:
    """Top-level runbooks, sorted by filename, hiding ``_``-prefixed fragments."""
    root = Path(runbooks_dir)
    paths: dict[str, Path] = {}
    for path in (*sorted(root.glob("*.yaml")), *sorted(root.glob("*.yml"))):
        if not path.stem.startswith("_"):
            paths.setdefault(path.stem, path)
    return [load_runbook(paths[stem]) for stem in sorted(paths)]


def interpolate(text: str, variables: Mapping[str, str]) -> str:
    """Replace ``{{ name }}`` tokens, including ``{{ env.NAME }}`` lookups."""

    def resolve(match: re.Match[str]) -> str:
        token = match.group(1)
        if token.startswith("env."):
            key = token.removeprefix("env.")
            if key not in os.environ:
                raise RunbookError(f"undefined environment variable '{key}'")
            return os.environ[key]
        if token not in variables:
            raise RunbookError(f"undefined variable '{token}'")
        return str(variables[token])

    return _VAR_RE.sub(resolve, text)


def _runbook_path(runbooks_dir: Path, entry: str) -> Path:
    root = runbooks_dir.resolve()
    names = [entry] if entry.endswith((".yaml", ".yml")) else [f"{entry}.yaml", f"{entry}.yml"]
    for name in names:
        candidate = (root / name).resolve()
        if root not in candidate.parents:
            raise RunbookError(f"include path escapes runbooks directory: {entry}")
        if candidate.is_file():
            return candidate
    return (root / names[0]).resolve()


def resolve_plan(
    entry: str,
    runbooks_dir: str | Path,
    *,
    cli_vars: Mapping[str, str] | None = None,
) -> list[PlanStep]:
    """Resolve includes and variables into a flat list of steps ready to execute."""
    return _resolve(
        entry=entry,
        runbooks_dir=Path(runbooks_dir),
        cli_vars=dict(cli_vars or {}),
        inherited={},
        stack=(),
    )


def _resolve(
    *,
    entry: str,
    runbooks_dir: Path,
    cli_vars: dict[str, str],
    inherited: dict[str, str],
    stack: tuple[Path, ...],
) -> list[PlanStep]:
    path = _runbook_path(runbooks_dir, entry)
    if path in stack:
        chain = " -> ".join(p.name for p in (*stack, path))
        raise RunbookError(f"circular include detected: {chain}")

    runbook = load_runbook(path)
    selected = {**runbook.vars, **inherited}
    variables = {**selected, **cli_vars}

    plan: list[PlanStep] = []
    for step in runbook.steps:
        if step.include is not None:
            plan.extend(
                _resolve(
                    entry=step.include,
                    runbooks_dir=runbooks_dir,
                    cli_vars=cli_vars,
                    inherited={**selected, **step.vars},
                    stack=(*stack, path),
                )
            )
            continue

        assert step.run is not None
        host = interpolate(step.host, variables) if step.host is not None else None
        plan.append(
            PlanStep(
                name=step.name,
                command=interpolate(step.run, variables),
                host=host,
                confirm=step.confirm,
            )
        )
    return plan
