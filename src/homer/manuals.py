from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bashlex
from bashlex.errors import ParsingError

MAX_MANUALS = 3
MAX_PAGE_CHARS = 5_000
MAX_TOTAL_CHARS = 15_000
MAN_TIMEOUT_SECONDS = 2.0

_COMMAND_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_SHELL_BUILTINS = frozenset(
    {
        "alias",
        "bg",
        "break",
        "builtin",
        "cd",
        "command",
        "continue",
        "dirs",
        "disown",
        "echo",
        "eval",
        "exec",
        "exit",
        "export",
        "false",
        "fc",
        "fg",
        "getopts",
        "hash",
        "jobs",
        "let",
        "local",
        "popd",
        "printf",
        "pushd",
        "pwd",
        "read",
        "readonly",
        "return",
        "set",
        "shift",
        "source",
        "test",
        "times",
        "trap",
        "true",
        "type",
        "typeset",
        "ulimit",
        "umask",
        "unalias",
        "unset",
        "wait",
        "whence",
    }
)


@dataclass(frozen=True)
class ManualExcerpt:
    command: str
    text: str


class ManualLookupError(RuntimeError):
    """Raised when the local manual system cannot be read reliably."""


def _walk_commands(node: Any) -> list[str]:
    if getattr(node, "kind", None) == "command":
        for part in getattr(node, "parts", []):
            if getattr(part, "kind", None) != "word":
                continue
            if getattr(part, "parts", []):
                return []
            name = getattr(part, "word", "")
            return [name] if isinstance(name, str) else []
        return []

    names: list[str] = []
    for value in vars(node).values():
        if isinstance(value, list):
            for item in value:
                if hasattr(item, "kind"):
                    names.extend(_walk_commands(item))
        elif hasattr(value, "kind"):
            names.extend(_walk_commands(value))
    return names


def command_names(command: str) -> tuple[str, ...]:
    """Return unique external command names suitable for local manual lookup."""
    try:
        trees = bashlex.parse(command)
    except (ParsingError, ValueError, NotImplementedError):
        return ()

    names: list[str] = []
    for tree in trees:
        for name in _walk_commands(tree):
            if name in _SHELL_BUILTINS or not _COMMAND_NAME.fullmatch(name) or name in names:
                continue
            names.append(name)
            if len(names) == MAX_MANUALS:
                return tuple(names)
    return tuple(names)


def _plain_text(content: str) -> str:
    content = _ANSI_ESCAPE.sub("", content.replace("\r", ""))
    while "\b" in content:
        content = re.sub(r".\x08", "", content)
    return content.replace("\f", "\n").strip()


class MacOSManual:
    def __init__(
        self,
        man_path: Path = Path("/usr/bin/man"),
        *,
        timeout_seconds: float = MAN_TIMEOUT_SECONDS,
        max_page_chars: int = MAX_PAGE_CHARS,
        max_total_chars: int = MAX_TOTAL_CHARS,
    ) -> None:
        self.man_path = man_path
        self.timeout_seconds = timeout_seconds
        self.max_page_chars = max_page_chars
        self.max_total_chars = max_total_chars

    def lookup(self, command: str) -> tuple[ManualExcerpt, ...]:
        remaining = self.max_total_chars
        excerpts: list[ManualExcerpt] = []
        environment = {
            **os.environ,
            "LC_ALL": "C",
            "MANPAGER": "cat",
            "PAGER": "cat",
        }

        for name in command_names(command):
            try:
                result = subprocess.run(
                    [str(self.man_path), name],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                    env=environment,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise ManualLookupError(
                    f"Could not read the local manual for {name}: {exc}"
                ) from exc
            if result.returncode != 0:
                continue

            text = _plain_text(result.stdout)
            limit = min(self.max_page_chars, remaining)
            if not text or limit <= 0:
                continue
            excerpt = text[:limit].rstrip()
            excerpts.append(ManualExcerpt(name, excerpt))
            remaining -= len(excerpt)
            if remaining <= 0:
                break

        return tuple(excerpts)
