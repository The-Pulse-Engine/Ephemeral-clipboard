import subprocess
import sys

import pytest

from eclip.cli import build_parser


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


def test_serve_limits_must_be_above_zero() -> None:
    for flag in ("--ttl", "--max-rooms", "--max-ip-connections", "--max-message"):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["serve", flag, "0"])
    args = build_parser().parse_args(["serve", "--ttl", "0.5", "--max-rooms", "3"])
    assert (args.ttl, args.max_rooms) == (0.5, 3)
