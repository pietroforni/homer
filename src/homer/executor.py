from __future__ import annotations

import subprocess
from pathlib import Path


class ExecutionError(RuntimeError):
    pass


def execute_command(command: str, cwd: Path) -> int:
    """Execute one confirmed command with zsh and inherited terminal streams."""
    try:
        completed = subprocess.run(
            ["/bin/zsh", "-lc", command],
            cwd=str(cwd),
            check=False,
        )
        return completed.returncode
    except KeyboardInterrupt:
        return 130
    except OSError as exc:
        raise ExecutionError(f"Could not start /bin/zsh: {exc}") from exc
