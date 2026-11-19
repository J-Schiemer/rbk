import rbk
from rbk.cli import main


def make_workspace(tmp_path):
    root = tmp_path / "ws"
    runbooks = root / "runbooks"
    runbooks.mkdir(parents=True)
    (runbooks / "update-immich.yaml").write_text(
        "name: Update Immich\ndescription: Pull and recreate.\nsteps: []\n",
        encoding="utf-8",
    )
    (runbooks / "second.yaml").write_text("name: Second\nsteps: []\n", encoding="utf-8")
    (runbooks / "_helper.yaml").write_text("name: Helper\nsteps: []\n", encoding="utf-8")
    return root


def test_version_flag_prints_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert capsys.readouterr().out.strip() == f"rbk {rbk.__version__}"


def test_package_version_matches_pyproject():
    assert rbk.__version__ == "0.1.0"


def test_run_without_implementation_exits_nonzero(capsys):
    assert main(["run", "thing"]) == 2
    assert "not implemented yet" in capsys.readouterr().err


def test_no_subcommand_prints_help(capsys):
    assert main([]) == 0
    assert "usage: rbk" in capsys.readouterr().out


def test_bad_var_is_rejected():
    try:
        main(["run", "thing", "--var", "novalue"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit for malformed --var")


def test_list_prints_top_level_runbooks(tmp_path, monkeypatch, capsys):
    root = make_workspace(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.delenv("RBK_DIR", raising=False)

    assert main(["list"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        f"{'second':<13}  Second",
        f"{'update-immich':<13}  Update Immich — Pull and recreate.",
    ]


def test_list_uses_dir_flag_from_elsewhere(tmp_path, monkeypatch, capsys):
    root = make_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["--dir", str(root), "list"]) == 0
    assert "update-immich" in capsys.readouterr().out


def test_list_uses_rbk_dir_env(tmp_path, monkeypatch, capsys):
    root = make_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RBK_DIR", str(root))

    assert main(["list"]) == 0
    assert "update-immich" in capsys.readouterr().out


def test_list_without_workspace_errors(tmp_path, capsys):
    assert main(["--dir", str(tmp_path), "list"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("rbk list:")
    assert "runbooks/" in err


def test_list_empty_workspace(tmp_path, capsys):
    root = tmp_path / "empty"
    (root / "runbooks").mkdir(parents=True)

    assert main(["--dir", str(root), "list"]) == 0
    assert "No runbooks found in" in capsys.readouterr().out
