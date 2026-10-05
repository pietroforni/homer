import re
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from homer.cli import _with_default_command, app
from homer.executor import ExecutionError
from homer.ollama import OllamaStatus
from homer.shell_assistant import CommandProposal

runner = CliRunner()
SAFE = CommandProposal("pwd", "Print the working directory.", ())
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def all_output(result: object) -> str:
    return ANSI_ESCAPE.sub("", result.stdout + result.stderr)  # type: ignore[attr-defined]


def test_help_presents_direct_workflow_and_secondary_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert 'homer "what is using port 8000?"' in result.stdout
    assert "write" in result.stdout
    assert "doctor" in result.stdout
    assert "install-completion" not in result.stdout
    assert "_shell" not in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "homer 0.2.0" in result.stdout


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], ["--help"]),
        (["where am I"], ["_shell", "where am I"]),
        (["--dry-run", "list files"], ["_shell", "--dry-run", "list files"]),
        (["--model", "small", "list files"], ["--model", "small", "_shell", "list files"]),
        (["--model=small", "list files"], ["--model=small", "_shell", "list files"]),
        (["write", "draft"], ["write", "draft"]),
        (["--help"], ["--help"]),
    ],
)
def test_default_command_routing(args: list[str], expected: list[str]) -> None:
    assert _with_default_command(args) == expected


def test_direct_request_supports_dry_run() -> None:
    with patch("homer.cli.ShellAssistant.propose", return_value=SAFE) as propose:
        result = runner.invoke(app, ["--dry-run", "where am I"])

    assert result.exit_code == 0
    assert "Proposed command" in result.stdout
    assert "Dry run" in result.stdout
    propose.assert_called_once_with("where am I")


def test_request_can_be_cancelled() -> None:
    with patch("homer.cli.ShellAssistant.propose", return_value=SAFE):
        result = runner.invoke(app, ["where am I"], input="\n")

    assert result.exit_code == 0
    assert "Cancelled" in result.stdout


def test_confirmed_request_executes() -> None:
    with (
        patch("homer.cli.ShellAssistant.propose", return_value=SAFE),
        patch("homer.cli.execute_command", return_value=0) as execute,
    ):
        result = runner.invoke(app, ["where am I"], input="y\n")

    assert result.exit_code == 0
    assert "completed successfully" in result.stdout
    execute.assert_called_once()


@pytest.mark.parametrize(
    ("exit_code", "message"),
    [(1, "status 1"), (130, "interrupted")],
)
def test_execution_status_is_reported(exit_code: int, message: str) -> None:
    with (
        patch("homer.cli.ShellAssistant.propose", return_value=SAFE),
        patch("homer.cli.execute_command", return_value=exit_code),
    ):
        result = runner.invoke(app, ["where am I"], input="y\n")

    assert result.exit_code == 1
    assert message in all_output(result).lower()


def test_execution_error_is_reported() -> None:
    with (
        patch("homer.cli.ShellAssistant.propose", return_value=SAFE),
        patch("homer.cli.execute_command", side_effect=ExecutionError("no shell")),
    ):
        result = runner.invoke(app, ["where am I"], input="y\n")

    assert result.exit_code == 1
    assert "Execution failed" in all_output(result)


def test_caution_is_displayed_before_confirmation() -> None:
    proposal = CommandProposal("rm old.txt", "Remove one file.", ("Check the path.",))
    with patch("homer.cli.ShellAssistant.propose", return_value=proposal):
        result = runner.invoke(app, ["remove the old file"], input="n\n")

    assert result.exit_code == 0
    assert "Caution" in result.stdout
    assert "Model warning" in result.stdout


def test_critical_command_is_always_blocked() -> None:
    proposal = CommandProposal("sudo rm old.txt", "Delete with privileges.", ())
    with (
        patch("homer.cli.ShellAssistant.propose", return_value=proposal),
        patch("homer.cli.execute_command") as execute,
    ):
        result = runner.invoke(app, ["delete the file"])

    assert result.exit_code == 1
    assert "never executes high-risk commands" in all_output(result)
    execute.assert_not_called()


def test_rejected_model_response_is_reported() -> None:
    with patch("homer.cli.ShellAssistant.propose", side_effect=ValueError("bad response")):
        result = runner.invoke(app, ["request"])

    assert result.exit_code == 1
    assert "Request rejected" in all_output(result)


def test_no_argument_shows_help() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert 'homer "what is using port 8000?"' in result.stdout


@pytest.mark.parametrize("removed", ["--config", "--ollama-host"])
def test_removed_configuration_options_are_rejected(removed: str) -> None:
    result = runner.invoke(app, [removed, "value", "doctor"])

    assert result.exit_code == 2
    assert "No such option" in all_output(result)


def test_model_override_is_used_for_one_request() -> None:
    with (
        patch("homer.cli.ShellAssistant.propose", return_value=SAFE),
        patch("homer.cli._client") as client,
    ):
        result = runner.invoke(app, ["--model", "small-model", "--dry-run", "where am I"])

    assert result.exit_code == 0
    client.assert_called_once_with("small-model")


def test_write_prints_generated_text() -> None:
    with patch("homer.cli._generate_writing", return_value="Finished text"):
        result = runner.invoke(app, ["write", "Draft a note"])

    assert result.exit_code == 0
    assert "Finished text" in result.stdout


def test_write_reads_input_and_saves_output(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    target = tmp_path / "result.md"
    style = tmp_path / "style.md"
    source.write_text("Original", encoding="utf-8")
    style.write_text("Clear.", encoding="utf-8")

    with patch("homer.cli._generate_writing", return_value="Revised") as generate:
        result = runner.invoke(
            app,
            [
                "write",
                "--input",
                str(source),
                "--output",
                str(target),
                "--style-guide",
                str(style),
                "Improve it",
            ],
        )

    assert result.exit_code == 0
    assert target.read_text(encoding="utf-8") == "Revised\n"
    assert generate.call_args.kwargs["input_text"] == "Original"


def test_write_refuses_existing_output(tmp_path: Path) -> None:
    target = tmp_path / "result.md"
    target.write_text("Keep", encoding="utf-8")

    with patch("homer.cli._generate_writing", return_value="Replace"):
        result = runner.invoke(app, ["write", "--output", str(target), "Rewrite"])

    assert result.exit_code == 1
    assert "already exists" in all_output(result)
    assert target.read_text(encoding="utf-8") == "Keep"


def test_write_force_requires_output() -> None:
    result = runner.invoke(app, ["write", "--force", "Draft"])

    assert result.exit_code == 2
    assert "--force requires --output" in all_output(result)


def test_write_requires_a_request() -> None:
    result = runner.invoke(app, ["write"])

    assert result.exit_code == 2
    assert "Missing argument" in all_output(result)


class StatusClient:
    def __init__(self, status: OllamaStatus) -> None:
        self._status = status

    def __enter__(self) -> "StatusClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def status(self) -> OllamaStatus:
        return self._status


def test_doctor_passes_when_model_is_available() -> None:
    status = OllamaStatus(True, ("qwen2.5:7b",))
    with patch("homer.cli._client", return_value=StatusClient(status)):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "OK" in result.stdout


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (OllamaStatus(False, error="offline"), "unavailable"),
        (OllamaStatus(True, ("another-model",)), "not found"),
    ],
)
def test_doctor_reports_failures(status: OllamaStatus, message: str) -> None:
    with patch("homer.cli._client", return_value=StatusClient(status)):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert message in all_output(result)
