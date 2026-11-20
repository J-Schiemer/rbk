# rbk

**A lightweight, Git-native CLI runbook runner for heterogeneous homelab infrastructure.**

`rbk` executes imperative, composable YAML workflows over standard OpenSSH — no agents, no Python, no daemons on your target hosts. Just `sh` and an SSH server.

## Why not Ansible?

Configuration management tools are excellent at declarative state convergence across uniform fleets. They are heavy when what you actually have is a handful of mismatched machines — a Synology NAS, a BSD router, three Linux boxes running `docker compose`, and one Alpine appliance — and what you actually need is a documented, repeatable sequence of commands.

`rbk` is that middle ground: a runbook runner, not a configuration language.

- **Zero target-host dependencies** — only POSIX `sh`/`bash` and OpenSSH. Nothing is installed remotely.
- **Embraces heterogeneity** — each runbook can be tailored per host, OS, architecture, and container runtime.
- **One dependency** — `pyyaml`. Everything else is the Python 3.11+ standard library.
- **Git-native** — runbooks are plain YAML files in a normal repo, completely decoupled from the binary.
- **Auditable** — every run appends to a local `.rbk-history.jsonl` trail.

## Installation

Until the first tagged release, run it from a checkout:

```sh
git clone https://github.com/J-Schiemer/rbk
cd rbk
uv run rbk --version
```

Once released, the planned install paths are:

```sh
brew tap J-Schiemer/tap && brew install rbk   # Homebrew
uv tool install git+https://github.com/J-Schiemer/rbk
```

## Quickstart

The target workflow. `rbk list`, `rbk run`, and `rbk record` are implemented.

Create a runbook workspace anywhere:

```text
homelab-runbooks/
└── runbooks/
    └── update-immich.yaml
```

```yaml
name: Update Immich
description: Pull new images, recreate the stack, then verify health.

vars:
  host: media-server
  stack_dir: /opt/stacks/immich

steps:
  - name: Confirm container recreation
    confirm: true
    host: "{{ host }}"
    run: |
      cd {{ stack_dir }}
      docker compose pull
      docker compose up -d

  - name: Wait for the API
    host: "{{ host }}"
    run: |
      for i in $(seq 1 15); do
        curl -sf http://localhost:2283/api/server/ping && exit 0
        sleep 2
      done
      exit 1
```

```sh
rbk list                     # top-level runbooks (helper _fragments hidden)
rbk run update-immich        # execute it
rbk run update-immich --dry-run
rbk run update-immich --var host=nuc
rbk record "Rotate TLS certs" --output runbooks/rotate-tls.yaml --host web-01  # capture a session as a runbook
```

Workspace discovery will walk up from `$PWD` looking for a `runbooks/` directory, the way `git` looks for `.git/`. Override with `--dir <path>` or `RBK_DIR`.

## Commands

| Command | Description |
| :--- | :--- |
| `rbk list` | List top-level runbooks, excluding `_`-prefixed fragments. |
| `rbk run <name>` | Execute `runbooks/<name>.yaml` (`.yaml` suffix optional). |
| `rbk run <name> --dry-run` | Resolve includes and variables, print the plan only. |
| `rbk run <name> --var k=v` | Override a variable at runtime (repeatable). |
| `rbk run <name> --yes` | Approve all `confirm` steps without prompting (for scripted runs). |
| `rbk record "<title>" --output <path>` | Record a local shell session into a runbook (path defaults to `runbooks/<slug>.yaml`). |
| `rbk record "<title>" --output <path> --host <alias>` | Record a remote `ssh -t` session into the given runbook path. |
| `rbk --version` | Print the version. |

Step keys: `name`, `run`, `host`, `include`, `vars`, `confirm`. `host` is a plain SSH destination (`[user@]host[:port]`) resolved by your usual OpenSSH config. Variables resolve `{{ name }}` from CLI `--var`, then variables selected by the caller (parent runbook `vars` + `include` vars), then runbook `vars`. Secrets stay out of Git via `{{ env.VAR_NAME }}`. `--output` is optional and defaults to `runbooks/<slugified-title>.yaml`. A `confirm` step needs a terminal; non-interactive runs must pass `--yes` or `rbk` aborts before executing anything.

## Status

This repository is a working tool: the CLI surface and packaging are in place, the core YAML layer (loading, schema validation, `{{ }}` interpolation, and `include` resolution with cycle detection) lives in `src/rbk/runbook.py`, workspace discovery (`--dir`, `$RBK_DIR`, upward walk) and `rbk list` in `src/rbk/workspace.py` and `src/rbk/cli.py`, and the execution engine in `src/rbk/executor.py`. `rbk run` executes steps locally via `sh` or over `ssh` with connection multiplexing, streams output live, aborts on the first failure while propagating its exit code, and appends an audit entry to `.rbk-history.jsonl`. The interactive session recorder is in `src/rbk/recorder.py`.

## Contributing

See [AGENTS.md](AGENTS.md) for the layout, commands, and hard design constraints (dependency budget, no YAML control-flow DSL, strict scope discipline).

## License

MIT — see [LICENSE](LICENSE).
