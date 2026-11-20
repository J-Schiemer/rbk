import shlex
import subprocess
from pathlib import Path

import pytest

import rbk.recorder as recorder
from rbk.cli import main
from rbk.recorder import (
    _capture_local,
    _capture_remote,
    _parse_history,
    _step_name,
    _triage,
    _write_yaml,
    record,
    slugify,
)
from rbk.runbook import RunbookError, Step, load_runbook


def feed(*answers: str):
    iterator = iter(answers)
    return lambda prompt: next(iterator)


def quiet(*args, **kwargs) -> None:
    pass


def test_parse_history_drops_blanks_and_consecutive_duplicates():
    text = "echo a\n\necho a\necho b\n  \n"
    assert _parse_history(text) == ["echo a", "echo b"]


def test_triage_keeps_by_default_and_discards_on_n():
    commands = ["echo keep", "echo drop", "echo edit me"]
    inputs = feed("", "n", "e", "echo edited", "")
    steps = _triage(commands, input_fn=inputs, print_fn=quiet)
    assert [step.run for step in steps] == ["echo keep", "echo edited"]
    assert [step.name for step in steps] == ["echo keep", "echo edited"]


def test_triage_edit_can_customize_step_name():
    inputs = feed("e", "echo edited", "Custom Name")
    steps = _triage(["echo original"], input_fn=inputs, print_fn=quiet)
    assert steps[0].run == "echo edited"
    assert steps[0].name == "Custom Name"


def test_triage_stops_gracefully_on_eof():
    remaining = ["echo one", "echo two"]
    answers = iter([""])

    def input_fn(prompt: str) -> str:
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    steps = _triage(remaining, input_fn=input_fn, print_fn=quiet)
    assert [step.run for step in steps] == ["echo one"]


def test_triage_keeps_multiline_command():
    command = "cd /opt\nmake deploy"
    steps = _triage([command], input_fn=feed(""), print_fn=quiet)
    assert steps[0].run == command


def test_step_name_truncates_and_falls_back():
    assert _step_name("  echo    hello  ") == "echo hello"
    assert _step_name("x" * 100).endswith("...")
    assert len(_step_name("x" * 100)) == 70
    assert _step_name("   ") == "step"


def test_write_yaml_uses_block_scalar_and_round_trips(tmp_path):
    path = tmp_path / "recorded.yaml"
    steps = [Step(name="multi", run="cd /tmp\necho hi"), Step(name="single", run="echo ok")]
    _write_yaml(path, "My Run", "web-01", steps)

    text = path.read_text(encoding="utf-8")
    assert "run: |" in text
    assert "run: echo ok" in text

    runbook = load_runbook(path)
    assert runbook.name == "My Run"
    assert "from web-01" in runbook.description
    assert runbook.steps[0].run == "cd /tmp\necho hi\n"
    assert runbook.steps[0].host == "web-01"
    assert runbook.steps[1].run == "echo ok"


def test_write_yaml_omits_host_for_local(tmp_path):
    path = tmp_path / "recorded.yaml"
    _write_yaml(path, "Local", None, [Step(name="one", run="echo hi")])
    assert load_runbook(path).steps[0].host is None


def test_record_refuses_overwrite_when_declined(tmp_path, monkeypatch):
    path = tmp_path / "runbook.yaml"
    path.write_text("name: Existing\nsteps: []\n", encoding="utf-8")
    monkeypatch.setattr(recorder, "_capture_local", pytest.fail)

    assert record("New", path, input_fn=feed("n"), print_fn=quiet) == 1
    assert "Existing" in path.read_text(encoding="utf-8")


def test_record_writes_requested_path(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "runbook.yaml"
    monkeypatch.setattr(recorder, "_capture_local", lambda: ["echo hi"])

    assert record("New", path, input_fn=feed(""), print_fn=quiet) == 0
    runbook = load_runbook(path)
    assert runbook.name == "New"
    assert runbook.steps[0].run == "echo hi"


def test_record_writes_nothing_when_all_discarded(tmp_path, monkeypatch):
    path = tmp_path / "runbook.yaml"
    monkeypatch.setattr(recorder, "_capture_local", lambda: ["echo hi"])

    assert record("New", path, input_fn=feed("n"), print_fn=quiet) == 1
    assert not path.exists()


def test_capture_local_uses_isolated_history(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder.shutil, "which", lambda name: "/bin/bash")

    def fake_run(argv, **kwargs):
        rcfile = Path(argv[2])
        text = rcfile.read_text(encoding="utf-8")
        assert "PROMPT_COMMAND='history -a'" in text
        assert ". ~/.bashrc" in text
        line = next(line for line in text.splitlines() if line.startswith("export HISTFILE="))
        histfile = Path(shlex.split(line.removeprefix("export "))[0].split("=", 1)[1])
        histfile.write_text("echo recorded\nexit\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(recorder.subprocess, "run", fake_run)
    assert _capture_local() == ["echo recorded", "exit"]


def test_capture_local_requires_bash(monkeypatch):
    monkeypatch.setattr(recorder.shutil, "which", lambda name: None)
    with pytest.raises(RunbookError, match="bash"):
        _capture_local()


def test_capture_remote_fetches_and_removes_history(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if "cat " in argv[-1]:
            return subprocess.CompletedProcess(argv, 0, stdout="echo hi\n", stderr="")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(recorder.subprocess, "run", fake_run)
    assert _capture_remote("web-01") == ["echo hi"]
    assert calls[0][:3] == ["ssh", "-t", "web-01"]
    assert calls[-1][:2] == ["ssh", "web-01"]
    assert calls[-1][-1].startswith("rm -f /tmp/rbk-record-")


def test_cli_record_dispatches(tmp_path, monkeypatch):
    called = {}

    def fake_record(title, output, host):
        called.update(title=title, output=output, host=host)
        return 0

    monkeypatch.setattr("rbk.cli.record", fake_record)
    assert main(["record", "My Title", "-o", str(tmp_path / "r.yaml")]) == 0
    assert called == {"title": "My Title", "output": tmp_path / "r.yaml", "host": None}


def test_cli_record_defaults_output_into_runbooks(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    (root / "runbooks").mkdir(parents=True)
    called = {}

    def fake_record(title, output, host):
        called.update(title=title, output=output, host=host)
        return 0

    monkeypatch.setattr("rbk.cli.record", fake_record)
    assert main(["--dir", str(root), "record", "Rotate TLS Certs"]) == 0
    assert called == {
        "title": "Rotate TLS Certs",
        "output": root / "runbooks" / "rotate-tls-certs.yaml",
        "host": None,
    }


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Rotate TLS Certs", "rotate-tls-certs"),
        ("  Update Immich! ", "update-immich"),
        ("a//b", "a-b"),
        ("42", "42"),
    ],
)
def test_slugify(title, expected):
    assert slugify(title) == expected


def test_slugify_empty_title_raises():
    with pytest.raises(RunbookError, match="filename"):
        slugify("!!!")
