"""Interactive session recorder: capture a shell session and compile a runbook."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path

import yaml

from rbk.runbook import RunbookError, Step, load_runbook

_HISTORY_LIMIT = 10_000


class _LiteralDumper(yaml.SafeDumper):
    """Dump multi-line strings as ``|`` block scalars."""


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_LiteralDumper.add_representer(str, _represent_str)


def slugify(title: str) -> str:
    """Derive a runbook filename stem from a title, raising if nothing remains."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    if not slug:
        raise RunbookError(f"cannot derive a runbook filename from title {title!r}")
    return slug


def record(
    title: str,
    output: Path,
    host: str | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[..., None] = print,
) -> int:
    """Capture a shell session, triage its commands, and write a runbook YAML."""
    output = Path(output).expanduser()
    if output.exists():
        answer = input_fn(f"{output} exists. Overwrite? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print_fn("Aborted; runbook not written.")
            return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    commands = _capture_remote(host) if host else _capture_local()
    steps = _triage(commands, input_fn=input_fn, print_fn=print_fn)
    if not steps:
        print_fn("No steps kept; runbook not written.")
        return 1

    _write_yaml(output, title, host, steps)
    load_runbook(output)
    plural = "step" if len(steps) == 1 else "steps"
    print_fn(f"Recorded {len(steps)} {plural} to {output}")
    return 0


def _capture_local() -> list[str]:
    bash = shutil.which("bash")
    if bash is None:
        raise RunbookError("bash is required to record a local session")

    workdir = Path(tempfile.mkdtemp(prefix="rbk-record-"))
    histfile = workdir / "history"
    rcfile = workdir / "bashrc"
    histfile.touch()
    rcfile.write_text(
        "[ -f ~/.bashrc ] && . ~/.bashrc\n"
        f"export HISTFILE={shlex.quote(str(histfile))}\n"
        f"export HISTSIZE={_HISTORY_LIMIT}\n"
        f"export HISTFILESIZE={_HISTORY_LIMIT}\n"
        "export PROMPT_COMMAND='history -a'\n"
        "unset HISTTIMEFORMAT\n"
        "shopt -u lithist 2>/dev/null\n",
        encoding="utf-8",
    )
    try:
        subprocess.run([bash, "--rcfile", str(rcfile), "-i"], check=False)
        return _parse_history(histfile.read_text(encoding="utf-8", errors="replace"))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _capture_remote(host: str) -> list[str]:
    remote_path = f"/tmp/rbk-record-{uuid.uuid4().hex}.hist"
    quoted = shlex.quote(remote_path)
    session = (
        f"export HISTFILE={quoted}; export HISTSIZE={_HISTORY_LIMIT}; "
        f"export HISTFILESIZE={_HISTORY_LIMIT}; unset HISTTIMEFORMAT; "
        "export PROMPT_COMMAND='history -a'; shopt -u lithist 2>/dev/null; exec bash -i"
    )
    try:
        result = subprocess.run(["ssh", "-t", host, session], check=False)
        if result.returncode != 0:
            raise RunbookError(f"ssh to {host} exited with status {result.returncode}")
        fetched = subprocess.run(
            ["ssh", host, f"cat {quoted}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if fetched.returncode != 0:
            detail = fetched.stderr.strip() or f"exit status {fetched.returncode}"
            raise RunbookError(f"could not read history from {host}: {detail}")
        return _parse_history(fetched.stdout)
    finally:
        subprocess.run(["ssh", host, f"rm -f {quoted}"], capture_output=True, check=False)


def _parse_history(text: str) -> list[str]:
    commands: list[str] = []
    for line in text.splitlines():
        command = line.rstrip()
        if not command:
            continue
        if commands and command == commands[-1]:
            continue
        commands.append(command)
    return commands


def _triage(
    commands: list[str],
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[..., None] = print,
) -> list[Step]:
    if not commands:
        print_fn("No commands captured.")
        return []

    print_fn(f"Captured {len(commands)} command(s). [Y] keep  [n] discard  [e] edit")
    steps: list[Step] = []
    try:
        for command in commands:
            print_fn(f"\n  {command}")
            choice = input_fn("Keep [Y/n/e]? ").strip().lower()
            if choice == "n":
                continue
            if choice == "e":
                command = input_fn("command> ").strip() or command
            if command.strip():
                steps.append(Step(name=_step_name(command), run=command))
    except (EOFError, KeyboardInterrupt):
        print_fn("")
    return steps


def _step_name(command: str) -> str:
    first = command.strip().splitlines()[0] if command.strip() else ""
    name = " ".join(first.split())
    if len(name) > 70:
        name = f"{name[:67].rstrip()}..."
    return name or "step"


def _write_yaml(path: Path, title: str, host: str | None, steps: list[Step]) -> None:
    origin = f"from {host}" if host else "locally"
    document = {
        "name": title,
        "description": f"Recorded {origin} on {date.today().isoformat()}.",
        "steps": [_step_document(step, host) for step in steps],
    }
    path.write_text(
        yaml.dump(document, Dumper=_LiteralDumper, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _step_document(step: Step, host: str | None) -> dict[str, str]:
    command = step.run or ""
    if "\n" in command and not command.endswith("\n"):
        command += "\n"
    document = {"name": step.name, "run": command}
    if host:
        document["host"] = host
    return document
