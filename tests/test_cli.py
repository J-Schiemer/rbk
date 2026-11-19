import rbk
from rbk.cli import main


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
