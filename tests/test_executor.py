import json
from pathlib import Path

import pytest

from rbk.executor import execute
from rbk.runbook import RunbookError


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "runbooks").mkdir(parents=True)
    return root


def write(workspace: Path, name: str, body: str) -> Path:
    path = workspace / "runbooks" / f"{name}.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def history(workspace: Path) -> list[dict]:
    path = workspace / ".rbk-history.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_dry_run_prints_plan_and_writes_no_history(workspace, capsys):
    write(workspace, "demo", "name: Demo\nsteps:\n  - name: Say hi\n    run: echo hi\n")

    assert execute("demo", workspace / "runbooks", dry_run=True) == 0

    out = capsys.readouterr().out
    assert "Plan for demo (1 step)" in out
    assert "Say hi [local]" in out
    assert "echo hi" in out
    assert not (workspace / ".rbk-history.jsonl").exists()


def test_local_success_runs_step_and_logs_history(workspace, capsys):
    write(workspace, "demo", "name: Demo\nsteps:\n  - name: Say hi\n    run: echo hi\n")

    assert execute("demo", workspace / "runbooks") == 0

    assert "[1/1] Say hi" in capsys.readouterr().out
    [entry] = history(workspace)
    assert entry["runbook"] == "demo"
    assert entry["hosts"] == ["local"]
    assert entry["status"] == "success"
    assert entry["failing_step"] is None
    assert isinstance(entry["duration"], float)
    assert entry["timestamp"].endswith("+00:00")


def test_local_failure_propagates_exit_code_and_stops(workspace):
    marker = workspace / "marker"
    write(
        workspace,
        "fail",
        "name: Fail\nsteps:\n"
        "  - name: Boom\n    run: exit 3\n"
        f"  - name: After\n    run: touch '{marker}'\n",
    )

    assert execute("fail", workspace / "runbooks") == 3

    assert not marker.exists()
    [entry] = history(workspace)
    assert entry["status"] == "failed"
    assert entry["failing_step"] == "Boom"


def test_confirm_declined_aborts(workspace):
    marker = workspace / "marker"
    write(
        workspace,
        "demo",
        f"name: Demo\nsteps:\n  - name: Touch\n    confirm: true\n    run: touch '{marker}'\n",
    )

    assert execute("demo", workspace / "runbooks", interactive=True, input_fn=lambda _: "") == 1

    assert not marker.exists()
    [entry] = history(workspace)
    assert entry["status"] == "failed"
    assert entry["failing_step"] == "Touch"


def test_confirm_accepted_runs_step(workspace):
    marker = workspace / "marker"
    write(
        workspace,
        "demo",
        f"name: Demo\nsteps:\n  - name: Touch\n    confirm: true\n    run: touch '{marker}'\n",
    )

    assert execute("demo", workspace / "runbooks", interactive=True, input_fn=lambda _: "y") == 0

    assert marker.exists()
    assert history(workspace)[0]["status"] == "success"


def test_non_interactive_confirm_fails_before_any_step(workspace):
    marker = workspace / "marker"
    write(
        workspace,
        "demo",
        f"name: Demo\nsteps:\n  - name: Touch\n    confirm: true\n    run: touch '{marker}'\n",
    )

    with pytest.raises(RunbookError, match="--yes"):
        execute("demo", workspace / "runbooks", interactive=False)

    assert not marker.exists()
    assert not (workspace / ".rbk-history.jsonl").exists()


def test_assume_yes_skips_prompt(workspace):
    marker = workspace / "marker"
    write(
        workspace,
        "demo",
        f"name: Demo\nsteps:\n  - name: Touch\n    confirm: true\n    run: touch '{marker}'\n",
    )

    assert execute("demo", workspace / "runbooks", interactive=False, assume_yes=True) == 0

    assert marker.exists()
    assert history(workspace)[0]["status"] == "success"


def test_dry_run_is_allowed_when_not_interactive(workspace, capsys):
    write(
        workspace,
        "demo",
        "name: Demo\nsteps:\n  - name: Touch\n    confirm: true\n    run: 'true'\n",
    )

    assert execute("demo", workspace / "runbooks", dry_run=True, interactive=False) == 0

    assert "Plan for demo (1 step)" in capsys.readouterr().out
    assert not (workspace / ".rbk-history.jsonl").exists()


def test_assume_yes_does_not_change_failure_propagation(workspace):
    write(
        workspace,
        "demo",
        "name: Demo\nsteps:\n  - name: Boom\n    confirm: true\n    run: exit 5\n",
    )

    assert execute("demo", workspace / "runbooks", interactive=False, assume_yes=True) == 5

    [entry] = history(workspace)
    assert entry["status"] == "failed"
    assert entry["failing_step"] == "Boom"


def test_history_is_append_only(workspace):
    write(workspace, "demo", "name: Demo\nsteps:\n  - name: Noop\n    run: 'true'\n")

    assert execute("demo", workspace / "runbooks") == 0
    assert execute("demo", workspace / "runbooks") == 0

    assert len(history(workspace)) == 2


def _capture_ssh(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Result()

    monkeypatch.setattr("rbk.executor.subprocess.run", fake_run)
    return calls


def test_remote_uses_controlmaster_options(workspace, monkeypatch):
    calls = _capture_ssh(monkeypatch)
    write(
        workspace,
        "demo",
        "name: Demo\nsteps:\n  - name: Remote\n    host: deploy@example.com\n    run: echo hi\n",
    )

    assert execute("demo", workspace / "runbooks") == 0

    argv = calls[0]
    assert "ControlMaster=auto" in argv
    assert "ControlPath=/tmp/rbk-%r@%h:%p" in argv
    assert "ControlPersist=60" in argv
    assert "deploy@example.com" in argv


def test_remote_host_with_port_passes_dash_p(workspace, monkeypatch):
    calls = _capture_ssh(monkeypatch)
    write(
        workspace,
        "demo",
        "name: Demo\nsteps:\n"
        "  - name: Remote\n    host: deploy@example.com:2222\n    run: echo hi\n",
    )

    assert execute("demo", workspace / "runbooks") == 0

    argv = calls[0]
    assert argv[argv.index("-p") + 1] == "2222"
    assert "deploy@example.com" in argv
    assert "deploy@example.com:2222" not in argv


def test_hosts_field_with_mixed_targets(workspace, monkeypatch):
    _capture_ssh(monkeypatch)
    write(
        workspace,
        "demo",
        "name: Demo\nsteps:\n"
        "  - name: Local\n    run: 'true'\n"
        "  - name: Remote\n    host: server\n    run: 'true'\n",
    )

    assert execute("demo", workspace / "runbooks") == 0
    assert history(workspace)[0]["hosts"] == ["local", "server"]
