from pathlib import Path
from unittest.mock import patch

import pytest

from homer.executor import ExecutionError, execute_command


def test_executor_uses_shell_without_extra_shell_layer(tmp_path: Path) -> None:
    with patch("homer.executor.subprocess.run") as run:
        run.return_value.returncode = 7
        code = execute_command("false", tmp_path)

    assert code == 7
    run.assert_called_once_with(
        ["/bin/zsh", "-lc", "false"],
        cwd=str(tmp_path),
        check=False,
    )


def test_executor_converts_os_error(tmp_path: Path) -> None:
    with patch("homer.executor.subprocess.run", side_effect=OSError("unavailable")):
        with pytest.raises(ExecutionError, match="Could not start /bin/zsh"):
            execute_command("pwd", tmp_path)


def test_executor_converts_keyboard_interrupt(tmp_path: Path) -> None:
    with patch("homer.executor.subprocess.run", side_effect=KeyboardInterrupt):
        assert execute_command("pwd", tmp_path) == 130
