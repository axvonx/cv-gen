from pathlib import Path

import pytest

from cv_gen.app import main as app_main
from cv_gen.cli import main


def test_list(capsys):
    assert main(["--list"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "4-bit CLA Adder Validation",
        "16-bit CLA Adder Validation",
        "16-bit ALU (2-bit Selector) Validation",
    ]


def test_alias_generates_csv_and_summary(tmp_path: Path, capsys):
    output = tmp_path / "cla4.csv"

    assert main(["-n", "cla4", "-i", "0", "-s", "42", str(output)]) == 0

    assert output.read_text().startswith("comb,4-bit CLA Adder Validation\n")
    assert "generated 1 case for '4-bit CLA Adder Validation'" in capsys.readouterr().out


def test_unknown_test_returns_failure(capsys, tmp_path: Path):
    assert main(["-n", "missing", "-i", "1", str(tmp_path / "out.csv")]) == 1
    assert "unknown test case: missing" in capsys.readouterr().err


def test_cv_gen_command_groups_and_no_old_aliases(capsys):
    assert app_main(["tests", "csv", "--list"]) == 0
    assert "4-bit CLA Adder Validation" in capsys.readouterr().out
    for args in (["cvt"], ["cv-testgen"], ["login"]):
        with pytest.raises(SystemExit) as error:
            app_main(args)
        assert error.value.code == 2
