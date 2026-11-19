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

The target workflow once the engine lands. Right now `rbk list`, `run`, and `record` exit with "not implemented yet" — see [Status](#status).

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
rbk record "Rotate TLS certs" --host web-01   # capture a session as a runbook
```

Workspace discovery will walk up from `$PWD` looking for `runbooks/` or `inventory.yaml`, the way `git` looks for `.git/`. Override with `--dir <path>` or `RBK_DIR`.

## Commands

| Command | Description |
| :--- | :--- |
| `rbk list` | List top-level runbooks, excluding `_`-prefixed fragments. |
| `rbk run <name>` | Execute `runbooks/<name>.yaml` (`.yaml` suffix optional). |
| `rbk run <name> --dry-run` | Resolve includes and variables, print the plan only. |
| `rbk run <name> --var k=v` | Override a variable at runtime (repeatable). |
| `rbk record "<title>"` | Record a local shell session into a new runbook. |
| `rbk record "<title>" --host <alias>` | Record a remote `ssh -t` session into a new runbook. |
| `rbk --version` | Print the version. |

Step keys: `name`, `run`, `host`, `include`, `vars`, `confirm`. Variables resolve `{{ name }}` from CLI `--var`, then parent `include` vars, then runbook `vars`, then `inventory.yaml`. Secrets stay out of Git via `{{ env.VAR_NAME }}`.

## Status

This repository is a skeleton: the CLI surface, packaging, and CI are in place, but the execution engine, recorder, and workspace discovery are not implemented yet. Unimplemented subcommands exit non-zero with a clear message.

## Contributing

See [AGENTS.md](AGENTS.md) for the layout, commands, and hard design constraints (dependency budget, no YAML control-flow DSL, strict scope discipline).

## License

MIT — see [LICENSE](LICENSE).
