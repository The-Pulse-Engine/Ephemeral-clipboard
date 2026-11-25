import subprocess
import sys


def test_help_lists_subcommands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "eclip.cli", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "send" in result.stdout
    assert "receive" in result.stdout
    assert "serve" in result.stdout


def test_unfinished_commands_exit_with_error() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "eclip.cli", "send"], capture_output=True, text=True
    )

    assert result.returncode == 1
    assert "not implemented" in result.stderr
