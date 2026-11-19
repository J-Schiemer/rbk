from pathlib import Path

import pytest

from rbk.runbook import (
    PlanStep,
    Runbook,
    RunbookError,
    interpolate,
    list_runbooks,
    load_runbook,
    resolve_plan,
)


@pytest.fixture
def runbooks(tmp_path: Path) -> Path:
    root = tmp_path / "runbooks"
    root.mkdir()
    return root


def write(root: Path, name: str, body: str) -> Path:
    path = root / f"{name}.yaml"
    path.write_text(body, encoding="utf-8")
    return path


VALID = """\
name: Update Immich
description: Pull images and recreate.
vars:
  host: media-server
  stack_dir: /opt/stacks/immich
steps:
  - name: Confirm
    confirm: true
    host: "{{ host }}"
    run: |
      cd {{ stack_dir }}
      docker compose pull
  - name: Helper
    include: _helper.yaml
"""


def test_load_valid_runbook(runbooks):
    path = write(runbooks, "main", VALID)
    runbook = load_runbook(path)
    assert isinstance(runbook, Runbook)
    assert runbook.name == "Update Immich"
    assert runbook.description == "Pull images and recreate."
    assert runbook.vars == {"host": "media-server", "stack_dir": "/opt/stacks/immich"}
    assert [step.name for step in runbook.steps] == ["Confirm", "Helper"]
    first, second = runbook.steps
    assert first.confirm is True
    assert first.host == "{{ host }}"
    assert first.run.startswith("cd {{ stack_dir }}")
    assert second.include == "_helper.yaml"
    assert second.run is None


@pytest.mark.parametrize(
    "body",
    ["steps: []\n", "name: ''\nsteps: []\n", "name: '   '\nsteps: []\n"],
)
def test_missing_or_empty_name(runbooks, body):
    path = write(runbooks, "bad", body)
    with pytest.raises(RunbookError, match="name"):
        load_runbook(path)


def test_missing_steps(runbooks):
    path = write(runbooks, "bad", "name: x\n")
    with pytest.raises(RunbookError, match="steps"):
        load_runbook(path)


def test_root_must_be_mapping(runbooks):
    path = write(runbooks, "bad", "- one\n- two\n")
    with pytest.raises(RunbookError, match="mapping"):
        load_runbook(path)


def test_unknown_top_level_key(runbooks):
    path = write(runbooks, "bad", "name: x\nsteps: []\nextra: true\n")
    with pytest.raises(RunbookError, match="unknown key"):
        load_runbook(path)


@pytest.mark.parametrize(
    ("step_body", "match"),
    [
        ("  - run: echo hi\n", "name"),
        ("  - name: s\n    run: echo hi\n    include: other.yaml\n", "exactly one"),
        ("  - name: s\n    host: host1\n", "exactly one"),
        ("  - name: s\n    run: echo hi\n    rn: typo\n", "unknown key"),
        ("  - name: s\n    run: echo hi\n    confirm: 'yes'\n", "boolean"),
        ("  - name: s\n    run: 42\n", "must be a string"),
    ],
)
def test_invalid_step(runbooks, step_body, match):
    path = write(runbooks, "bad", "name: x\nsteps:\n" + step_body)
    with pytest.raises(RunbookError, match=match):
        load_runbook(path)


def test_malformed_yaml(runbooks):
    path = write(runbooks, "bad", "name: [unclosed\n")
    with pytest.raises(RunbookError, match="invalid YAML"):
        load_runbook(path)


def test_nonexistent_file(runbooks):
    with pytest.raises(RunbookError, match="cannot read"):
        load_runbook(runbooks / "nope.yaml")


def test_interpolate_single_and_multiple():
    assert interpolate("echo {{ host }}", {"host": "h"}) == "echo h"
    assert interpolate("{{a}}-{{ b }}", {"a": "1", "b": "2"}) == "1-2"


def test_interpolate_undefined_variable():
    with pytest.raises(RunbookError, match="undefined variable 'x'"):
        interpolate("{{ x }}", {})


def test_interpolate_env(monkeypatch):
    monkeypatch.setenv("RBK_TOKEN", "secret")
    assert interpolate("{{ env.RBK_TOKEN }}", {}) == "secret"


def test_interpolate_missing_env(monkeypatch):
    monkeypatch.delenv("RBK_NOPE", raising=False)
    with pytest.raises(RunbookError, match="RBK_NOPE"):
        interpolate("{{ env.RBK_NOPE }}", {})


def test_resolve_plan_basic(runbooks):
    write(
        runbooks,
        "main",
        """\
name: Main
vars:
  who: world
  target: deploy@10.0.0.5
steps:
  - name: Greet
    host: "{{ target }}"
    run: echo hi {{ who }}
""",
    )
    assert resolve_plan("main", runbooks) == [
        PlanStep(name="Greet", command="echo hi world", host="deploy@10.0.0.5", confirm=False)
    ]


def test_include_flattens_steps(runbooks):
    write(
        runbooks,
        "main",
        """\
name: Main
steps:
  - name: before
    run: echo before
  - name: helper
    include: helper
  - name: after
    run: echo after
""",
    )
    write(runbooks, "helper", "name: Helper\nsteps:\n  - name: inner\n    run: echo inner\n")
    plan = resolve_plan("main", runbooks)
    assert [step.name for step in plan] == ["before", "inner", "after"]


def test_include_vars_override_parent_and_child(runbooks):
    write(
        runbooks,
        "main",
        """\
name: Main
vars:
  x: parent
steps:
  - name: inc
    include: child
    vars:
      x: include
""",
    )
    write(
        runbooks,
        "child",
        "name: Child\nvars:\n  x: child\nsteps:\n  - name: show\n    run: echo {{ x }}\n",
    )
    assert resolve_plan("main", runbooks)[0].command == "echo include"
    assert resolve_plan("main", runbooks, cli_vars={"x": "cli"})[0].command == "echo cli"


def test_child_uses_own_vars_by_default(runbooks):
    write(runbooks, "main", "name: Main\nsteps:\n  - name: inc\n    include: child\n")
    write(
        runbooks,
        "child",
        "name: Child\nvars:\n  x: child\nsteps:\n  - name: show\n    run: echo {{ x }}\n",
    )
    assert resolve_plan("main", runbooks)[0].command == "echo child"


def test_parent_vars_are_inherited_by_includes(runbooks):
    write(
        runbooks,
        "main",
        "name: Main\nvars:\n  x: parent\nsteps:\n  - name: inc\n    include: child\n",
    )
    write(
        runbooks,
        "child",
        "name: Child\nvars:\n  x: child\nsteps:\n  - name: show\n    run: echo {{ x }}\n",
    )
    assert resolve_plan("main", runbooks)[0].command == "echo parent"


def test_nested_includes_inherit_vars(runbooks):
    write(
        runbooks,
        "main",
        "name: Main\nsteps:\n  - name: inc\n    include: outer\n    vars:\n      a: '1'\n",
    )
    write(
        runbooks,
        "outer",
        "name: Outer\nsteps:\n  - name: inc\n    include: inner\n    vars:\n      b: '2'\n",
    )
    write(runbooks, "inner", "name: Inner\nsteps:\n  - name: show\n    run: echo {{ a }}-{{ b }}\n")
    assert resolve_plan("main", runbooks)[0].command == "echo 1-2"


def test_cycle_is_detected(runbooks):
    write(runbooks, "a", "name: A\nsteps:\n  - name: inc\n    include: b\n")
    write(runbooks, "b", "name: B\nsteps:\n  - name: inc\n    include: a\n")
    with pytest.raises(RunbookError, match="circular include") as exc:
        resolve_plan("a", runbooks)
    assert "a.yaml -> b.yaml -> a.yaml" in str(exc.value)


def test_include_cannot_escape_runbooks_dir(runbooks):
    write(runbooks, "main", "name: Main\nsteps:\n  - name: inc\n    include: ../evil.yaml\n")
    with pytest.raises(RunbookError, match="escapes"):
        resolve_plan("main", runbooks)


def test_list_runbooks_hides_fragments_and_sorts(runbooks):
    write(runbooks, "zeta", "name: Zeta\nsteps: []\n")
    write(runbooks, "alpha", "name: Alpha\nsteps: []\n")
    write(runbooks, "_fragment", "name: Fragment\nsteps: []\n")
    assert [runbook.path.stem for runbook in list_runbooks(runbooks)] == ["alpha", "zeta"]


def test_list_runbooks_includes_yml_files(runbooks):
    (runbooks / "extra.yml").write_text("name: Extra\nsteps: []\n", encoding="utf-8")
    assert [runbook.name for runbook in list_runbooks(runbooks)] == ["Extra"]


def test_list_runbooks_prefers_yaml_over_yml(runbooks):
    write(runbooks, "both", "name: FromYaml\nsteps: []\n")
    (runbooks / "both.yml").write_text("name: FromYml\nsteps: []\n", encoding="utf-8")
    assert [runbook.name for runbook in list_runbooks(runbooks)] == ["FromYaml"]


def test_list_runbooks_ignores_non_yaml_files(runbooks):
    (runbooks / "notes.md").write_text("hello", encoding="utf-8")
    assert list_runbooks(runbooks) == []


def test_list_runbooks_empty_directory(runbooks):
    assert list_runbooks(runbooks) == []


def test_list_runbooks_fails_fast_on_invalid_runbook(runbooks):
    write(runbooks, "broken", "name: [unclosed\n")
    with pytest.raises(RunbookError, match="broken.yaml"):
        list_runbooks(runbooks)
