from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import bashlex


class CommandValidationError(ValueError):
    """Raised when a command cannot be safely inspected."""


class RiskLevel(str, Enum):
    NORMAL = "normal"
    CAUTION = "caution"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SafetyReport:
    level: RiskLevel
    reasons: tuple[str, ...]


_CRITICAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|[;&|]\s*)\s*(sudo|doas|su)(\s|$)"), "privilege escalation"),
    (
        re.compile(
            r"\brm\b"
            r"(?=[^;&|]*(?:\s-[a-z]*r[a-z]*|\s--recursive)(?=\s|$))"
            r"(?=[^;&|]*(?:\s-[a-z]*f[a-z]*|\s--force)(?=\s|$))"
            r"[^;&|]*(?:^|\s|[\"'])(?:/|/\*|~/?|\$home|\$\{home\})(?:[\"']|\s|$)"
        ),
        "broad recursive deletion",
    ),
    (
        re.compile(r"\b(diskutil\s+(erase|partition)|mkfs(?:\.|\s)|newfs(?:\.|\s))"),
        "disk formatting or partitioning",
    ),
    (re.compile(r"\bdd\s+[^\n]*\bof=/dev/"), "raw device overwrite"),
    (re.compile(r"\bfind\b[^\n]*(?:-delete|-exec\s+rm)"), "destructive find operation"),
    (
        re.compile(r"\b(?:curl|wget)\b[^\n]*\|\s*(?:/[\w.-]+/)?(?:ba|z|fi)?sh\b"),
        "remote script execution",
    ),
    (re.compile(r"\b(?:eval|source)\b"), "dynamic or sourced shell code"),
    (re.compile(r"(?:`[^`]+`|\$\([^)]*\))"), "command substitution obscures the executed command"),
    (re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;\s*:"), "fork bomb"),
    (re.compile(r"\b(?:shutdown|reboot|halt)\b"), "system shutdown"),
    (
        re.compile(r"\b(?:chmod|chown)\s+-r\b[^\n]*(?:\s/\s*$|\s~/?\s*$|\$home)"),
        "broad recursive permission change",
    ),
)

_CAUTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|[;&|]\s*)\s*rm\b"), "deletes files or directories"),
    (re.compile(r"(^|[;&|]\s*)\s*(mv|cp)\b"), "changes filesystem contents"),
    (re.compile(r"(^|[;&|]\s*)\s*(chmod|chown|kill|pkill)\b"), "changes permissions or processes"),
    (re.compile(r"(^|[^>])>(?!>)"), "may overwrite a file through redirection"),
    (re.compile(r">>"), "appends to a file"),
    (re.compile(r"\b(curl|wget)\b"), "accesses the network"),
    (
        re.compile(r"\b(git\s+(push|clean|reset)|brew\s+(install|uninstall))\b"),
        "changes external or installed state",
    ),
)


def _syntax_check(command: str, shell: Path) -> None:
    try:
        result = subprocess.run(
            [str(shell), "-n", "-c", command],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CommandValidationError(f"Could not validate command syntax: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "unknown syntax error"
        raise CommandValidationError(f"Invalid shell syntax: {detail}")


def inspect_command(
    command: str,
    *,
    shell: Path = Path("/bin/zsh"),
) -> SafetyReport:
    if not command.strip():
        raise CommandValidationError("The generated command is empty.")
    if "\n" in command or "\r" in command or "\x00" in command:
        raise CommandValidationError("Multiline commands and NUL bytes are not supported.")
    if len(command) > 4096:
        raise CommandValidationError("The generated command is too long to inspect safely.")

    _syntax_check(command, shell)
    try:
        bashlex.parse(command)
    except (ValueError, NotImplementedError) as exc:
        raise CommandValidationError(
            f"The command uses shell syntax Homer cannot inspect safely: {exc}"
        ) from exc

    normalized = command.strip().lower()
    critical = tuple(reason for pattern, reason in _CRITICAL_PATTERNS if pattern.search(normalized))
    if critical:
        return SafetyReport(RiskLevel.CRITICAL, critical)

    caution = tuple(reason for pattern, reason in _CAUTION_PATTERNS if pattern.search(normalized))
    if caution:
        return SafetyReport(RiskLevel.CAUTION, caution)
    return SafetyReport(RiskLevel.NORMAL, ())
