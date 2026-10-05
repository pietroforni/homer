import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from homer.manuals import MacOSManual, ManualLookupError, command_names


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("du -sh ./* | sort -hr | head -n 5", ("du", "sort", "head")),
        ("MODE=quiet find . -name '*.py' > files.txt", ("find",)),
        ("find . && find /tmp && grep py files.txt", ("find", "grep")),
        ("cd /tmp && pwd", ()),
        ("/usr/bin/find .", ()),
        ("echo $(whoami)", ()),
        ("if then", ()),
    ],
)
def test_command_names_extracts_safe_external_utilities(
    command: str, expected: tuple[str, ...]
) -> None:
    assert command_names(command) == expected


def test_manual_lookup_cleans_and_bounds_output() -> None:
    pages = [
        subprocess.CompletedProcess([], 0, stdout="F\bFI\bIN\bND\n\x1b[31mNAME\x1b[0m\nabcdef"),
        subprocess.CompletedProcess([], 0, stdout="SORT\n123456"),
    ]
    manual = MacOSManual(max_page_chars=12, max_total_chars=16)

    with patch("homer.manuals.subprocess.run", side_effect=pages) as run:
        excerpts = manual.lookup("find . | sort")

    assert [(item.command, item.text) for item in excerpts] == [
        ("find", "FIND\nNAME\nab"),
        ("sort", "SORT"),
    ]
    assert run.call_count == 2
    assert run.call_args_list[0].args[0] == ["/usr/bin/man", "find"]
    assert run.call_args_list[0].kwargs["timeout"] == 2.0
    assert run.call_args_list[0].kwargs["env"]["MANPAGER"] == "cat"


def test_manual_lookup_skips_missing_pages() -> None:
    missing = subprocess.CompletedProcess([], 1, stdout="", stderr="No manual entry")
    manual = MacOSManual(man_path=Path("/usr/bin/man"))

    with patch("homer.manuals.subprocess.run", return_value=missing):
        assert manual.lookup("find .") == ()


def test_manual_lookup_reports_timeout() -> None:
    timeout = subprocess.TimeoutExpired(["/usr/bin/man", "find"], 2)
    manual = MacOSManual()

    with (
        patch("homer.manuals.subprocess.run", side_effect=timeout),
        pytest.raises(ManualLookupError, match="find"),
    ):
        manual.lookup("find .")
