# AGENTS.md

Guidance for agents and contributors working in this repository.

## What this is

`rbk` is a Git-native CLI runbook runner that executes YAML workflows over plain OpenSSH. It exists to fill the gap between one-off bash scripts and Ansible/Puppet/Salt: imperative, composable, documented command sequences for heterogeneous homelab hosts.

## Non-negotiable constraints

- **Python 3.11+**, standard library plus exactly one dependency: `pyyaml`. Adding any other runtime dependency requires explicit approval.
- **Core codebase budget ≈250 lines of Python.** Prefer deleting code over abstracting it.
- **No agents or runtimes on target hosts.** Remote steps assume only POSIX `sh`/`bash` and OpenSSH.
- **No YAML control-flow DSL.** No `when:`, `loop:`, `register:`, or conditional expressions. Loops and branches belong inside embedded shell blocks.
- **No daemon, web UI, or state convergence engine.** Synchronous single-user CLI only.
- **`rbk` is a workspace-owned tool; runbooks are user data.** Keep the engine free of hardcoded runbook paths.

## Layout

| Path | Purpose |
| :--- | :--- |
| `src/rbk/cli.py` | Argument parsing and command dispatch. |
| `src/rbk/runbook.py` | YAML loading/validation, `{{ }}` interpolation, include resolution, runbook listing. |
| `src/rbk/workspace.py` | Workspace discovery: `--dir` > `$RBK_DIR` > upward search for `runbooks/`. |
| `src/rbk/executor.py` | Plan printing, local/SSH step execution, audit log. |
| `src/rbk/recorder.py` | Interactive session capture, per-command triage, YAML writing. |
| `src/rbk/__init__.py` | Version string. |
| `tests/` | Pytest suite; CLI smoke tests live here. |
| `Formula/rbk.rb` | Homebrew tap formula (tap: `J-Schiemer/homebrew-tap`). |
| `.github/workflows/` | `ci.yml` (lint + test) and `release.yml` (tag → release → formula bump). |

## Commands

```sh
uv sync                     # create the venv and install deps
uv run rbk --version        # run the CLI from source
uv run pytest -q            # tests
uv run ruff check .         # lint
uv run ruff format --check .  # formatting
uv build                    # sdist + wheel into dist/
```

Run `ruff check`, `ruff format --check`, and `pytest` before considering work done; CI runs exactly these.

## Conventions

- **Fail fast.** Remote commands use `set -euo pipefail`, falling back to `set -e` on minimal shells such as BusyBox/Alpine. Non-zero exit codes abort the runbook and propagate.
- **Stream, never buffer.** Output goes straight to the terminal as it is produced.
- **SSH multiplexing is mandatory** for multi-step runs: pass `ControlMaster=auto`, `ControlPath=/tmp/rbk-%r@%h:%p`, `ControlPersist=60`.
- **Includes must detect cycles** by tracking the active call stack and aborting with a clear error.
- **Never write secrets into runbooks.** Resolve them at runtime via `{{ env.VAR_NAME }}`.
- **The audit log is append-only.** `.rbk-history.jsonl` is gitignored; entries are one JSON object per line with ISO-8601 timestamp, runbook, hosts, duration, status, and failing step. Do not break that shape.
- **Variable interpolation** uses `{{ name }}`; precedence is CLI `--var` > variables selected by the caller (parent runbook `vars` + `include` vars) > the runbook's own `vars`. There is no inventory file.

## Spec and local docs

`.docs/` is intentionally gitignored. It holds the full requirements specification (`TODO.md`) — read it before changing behavior, and never commit it. Do not add other files under `.docs/` unless asked.
