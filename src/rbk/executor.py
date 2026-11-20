"""Runbook execution: plan printing, local/SSH steps, and the audit log."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from rbk.runbook import PlanStep, RunbookError, resolve_plan

SSH_OPTIONS = (
    "-o",
    "ControlMaster=auto",
    "-o",
    "ControlPath=/tmp/rbk-%r@%h:%p",
    "-o",
    "ControlPersist=60",
)
HISTORY_FILE = ".rbk-history.jsonl"


def _script(command: str) -> str:
    """Prefix a step with fail-fast options, falling back to ``set -e``."""
    preamble = "if (set -o pipefail) 2>/dev/null; then set -euo pipefail; else set -e; fi\n"
    return preamble + command + "\n"


def _split_port(host: str) -> tuple[str, str | None]:
    if host.startswith("["):
        return host, None
    destination, sep, port = host.rpartition(":")
    if sep and destination and port.isdigit():
        return destination, port
    return host, None


def _run_local(command: str) -> int:
    shell = shutil.which("sh") or "sh"
    return subprocess.run([shell, "-c", _script(command)], check=False).returncode


def _run_remote(host: str, command: str) -> int:
    destination, port = _split_port(host)
    argv = ["ssh", *SSH_OPTIONS]
    if port:
        argv += ["-p", port]
    argv += ["--", destination, _script(command)]
    return subprocess.run(argv, check=False).returncode


def _format_plan(entry: str, plan: list[PlanStep]) -> str:
    plural = "step" if len(plan) == 1 else "steps"
    lines = [f"Plan for {entry} ({len(plan)} {plural})"]
    for index, step in enumerate(plan, 1):
        target = f"host: {step.host}" if step.host else "local"
        flags = ", confirm" if step.confirm else ""
        lines.append(f"{index}. {step.name} [{target}{flags}]")
        lines.extend(f"     {line}" for line in step.command.rstrip("\n").splitlines())
    return "\n".join(lines)


def _append_history(
    workspace_root: Path,
    entry: str,
    plan: list[PlanStep],
    duration: float,
    status: str,
    failing_step: str | None,
) -> None:
    record = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "runbook": entry,
        "hosts": sorted({step.host or "local" for step in plan}),
        "duration": round(duration, 3),
        "status": status,
        "failing_step": failing_step,
    }
    path = workspace_root / HISTORY_FILE
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"rbk: could not write {path}: {exc}", file=sys.stderr)


def execute(
    entry: str,
    runbooks_dir: str | Path,
    *,
    cli_vars: Mapping[str, str] | None = None,
    dry_run: bool = False,
    assume_yes: bool = False,
    interactive: bool | None = None,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[..., None] = print,
) -> int:
    """Resolve and execute a runbook, returning the propagated exit code."""
    plan = resolve_plan(entry, runbooks_dir, cli_vars=cli_vars)
    if dry_run:
        print_fn(_format_plan(entry, plan))
        return 0

    if interactive is None:
        interactive = sys.stdin.isatty()
    if not assume_yes and not interactive and any(step.confirm for step in plan):
        need = ", ".join(step.name for step in plan if step.confirm)
        raise RunbookError(
            f"runbook requires confirmation for {need}, but stdin is not a terminal; "
            "re-run with --yes to approve non-interactively"
        )

    started = time.monotonic()
    status = "success"
    failing_step: str | None = None
    exit_code = 0
    current: str | None = None

    try:
        for index, step in enumerate(plan, 1):
            current = step.name
            target = f" -> {step.host}" if step.host else ""
            print_fn(f"[{index}/{len(plan)}] {step.name}{target}", flush=True)
            if step.confirm and not assume_yes:
                answer = input_fn(f"{step.name}: run? [y/N] ").strip().lower()
                if answer not in {"y", "yes"}:
                    print_fn(f"Aborted at '{step.name}'.", flush=True)
                    status, failing_step, exit_code = "failed", step.name, 1
                    break
            if step.host:
                code = _run_remote(step.host, step.command)
            else:
                code = _run_local(step.command)
            if code != 0:
                print_fn(f"Step '{step.name}' failed with exit status {code}.", flush=True)
                status, failing_step, exit_code = "failed", step.name, code
                break
    except KeyboardInterrupt:
        print_fn("\nInterrupted.")
        status, failing_step, exit_code = "failed", current, 130
    finally:
        _append_history(
            Path(runbooks_dir).parent,
            entry,
            plan,
            time.monotonic() - started,
            status,
            failing_step,
        )

    if status == "success":
        print_fn(f"Completed {len(plan)} step{'s' if len(plan) != 1 else ''}.", flush=True)
    return exit_code
