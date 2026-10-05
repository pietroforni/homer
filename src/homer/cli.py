from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from typer.core import TyperGroup

from homer import __version__
from homer.executor import ExecutionError, execute_command
from homer.ollama import OllamaClient, OllamaError
from homer.safety import CommandValidationError, RiskLevel, inspect_command
from homer.shell_assistant import CommandProposal, ShellAssistant
from homer.writer import WritingAssistant, WritingError

DEFAULT_MODEL = "qwen2.5:7b"
OLLAMA_HOST = "http://localhost:11434"
TIMEOUT_SECONDS = 60.0
CONTEXT_TOKENS = 8192

_PUBLIC_COMMANDS = {"write", "doctor"}
_ROOT_VALUE_OPTIONS = {"--model"}
_ROOT_EXIT_OPTIONS = {
    "--help",
    "-h",
    "--version",
}


def _with_default_command(args: list[str]) -> list[str]:
    """Route bare requests to the hidden shell command while preserving subcommands."""
    if not args:
        return ["--help"]

    index = 0
    while index < len(args):
        token = args[index]
        if token in _ROOT_EXIT_OPTIONS or token in _PUBLIC_COMMANDS:
            return args
        if token in _ROOT_VALUE_OPTIONS:
            index += 2
            continue
        if any(token.startswith(f"{option}=") for option in _ROOT_VALUE_OPTIONS):
            index += 1
            continue
        return [*args[:index], "_shell", *args[index:]]
    return [*args, "_shell"]


class DefaultCommandGroup(TyperGroup):
    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:
        return super().parse_args(ctx, _with_default_command(args))


app = typer.Typer(
    name="homer",
    cls=DefaultCommandGroup,
    help="Turn plain-English requests into shell commands you can review before running.",
    epilog='Example: `homer "what is using port 8000?"`',
    no_args_is_help=False,
    add_completion=False,
    subcommand_metavar="[REQUEST] | COMMAND",
    pretty_exceptions_enable=False,
)

console = Console()
error_console = Console(stderr=True)


@dataclass(frozen=True)
class AppState:
    model: str


def _version(value: bool) -> None:
    if value:
        typer.echo(f"homer {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="Ollama model to use."),
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show the version."
    ),
) -> None:
    """Homer keeps model requests local and command execution under your control."""
    del version
    ctx.obj = AppState(model)


def _model(ctx: typer.Context) -> str:
    state: AppState = ctx.ensure_object(AppState)
    return state.model


def _client(model: str) -> OllamaClient:
    return OllamaClient(OLLAMA_HOST, model, TIMEOUT_SECONDS, CONTEXT_TOKENS)


def _show_proposal(proposal: CommandProposal) -> None:
    console.print("\n[bold]Proposed command[/]")
    console.print(Syntax(proposal.command, "bash", word_wrap=True))
    console.print("\n[bold]Explanation[/]")
    console.print(Text(proposal.explanation))
    if proposal.manuals:
        console.print(f"[dim]Consulted local manuals: {', '.join(proposal.manuals)}[/]")
    if proposal.manual_warning:
        console.print("[yellow]Manual warning:[/]", Text(proposal.manual_warning))
    for warning in proposal.warnings:
        console.print("[yellow]Model warning:[/]", Text(warning))


def _process_shell_request(request: str, model: str, *, dry_run: bool) -> bool:
    try:
        with _client(model) as client:
            proposal = ShellAssistant(client).propose(request)
        _show_proposal(proposal)
        report = inspect_command(proposal.command)
    except (OllamaError, CommandValidationError, ValueError) as exc:
        error_console.print(f"[bold red]Request rejected:[/] {exc}")
        return False

    if report.level is RiskLevel.CAUTION:
        console.print(Panel("\n".join(report.reasons), title="Caution", style="yellow"))
    elif report.level is RiskLevel.CRITICAL:
        console.print(Panel("\n".join(report.reasons), title="Blocked command", style="bold red"))
        error_console.print("[bold red]Blocked.[/] Homer never executes high-risk commands.")
        return False

    if dry_run:
        console.print("\n[cyan]Dry run: command was not executed.[/]")
        return True
    if not typer.confirm("Execute?", default=False):
        console.print("[dim]Cancelled; nothing was executed.[/]")
        return True

    try:
        code = execute_command(proposal.command, Path.cwd())
    except ExecutionError as exc:
        error_console.print(f"[bold red]Execution failed:[/] {exc}")
        return False
    if code == 130:
        error_console.print("[yellow]Command interrupted.[/]")
    elif code != 0:
        error_console.print(f"[yellow]Command exited with status {code}.[/]")
    else:
        console.print("[green]Command completed successfully.[/]")
    return code == 0


@app.command("_shell", hidden=True)
def shell(
    ctx: typer.Context,
    request: str = typer.Argument(..., help="Natural-language terminal request."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Generate and validate, but never execute."
    ),
) -> None:
    """Generate a shell command and require confirmation before execution."""
    if not _process_shell_request(request, _model(ctx), dry_run=dry_run):
        raise typer.Exit(1)


def _read_input(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WritingError(f"Could not read input file {path}: {exc}") from exc


def _save_output(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        raise WritingError(f"Output already exists: {path}. Use --force to replace it.")
    if not path.parent.exists():
        raise WritingError(f"Output directory does not exist: {path.parent}")
    try:
        path.write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8")
    except OSError as exc:
        raise WritingError(f"Could not write output file {path}: {exc}") from exc


def _generate_writing(
    request: str,
    model: str,
    style_guide: Path | None,
    *,
    input_text: str | None = None,
) -> str:
    with _client(model) as client:
        return WritingAssistant(client, style_guide, CONTEXT_TOKENS).generate(
            request, input_text=input_text
        )


@app.command()
def write(
    ctx: typer.Context,
    request: str = typer.Argument(..., help="Drafting or editing request."),
    input_path: Path | None = typer.Option(None, "--input", "-i", help="UTF-8 text file to edit."),
    output_path: Path | None = typer.Option(
        None, "--output", "-o", help="Save the result instead of printing it."
    ),
    style_guide: Path | None = typer.Option(
        None, "--style-guide", help="Use a custom writing style guide."
    ),
    force: bool = typer.Option(False, "--force", help="Replace an existing output file."),
) -> None:
    """Draft or edit text with Homer's small writing helper."""
    if force and output_path is None:
        raise typer.BadParameter("--force requires --output")

    try:
        source = _read_input(input_path.expanduser().resolve()) if input_path else None
        guide = style_guide.expanduser().resolve() if style_guide else None
        result = _generate_writing(
            request,
            _model(ctx),
            guide,
            input_text=source,
        )
        if output_path:
            target = output_path.expanduser().resolve()
            _save_output(target, result, force)
            console.print(f"[green]Saved:[/] {target}")
        else:
            console.print(Text(result))
    except (OllamaError, WritingError) as exc:
        error_console.print(f"[bold red]Writing failed:[/] {exc}")
        raise typer.Exit(1) from exc


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check zsh, local Ollama, and the selected model."""
    model = _model(ctx)
    failures = 0

    shell_path = Path("/bin/zsh")
    if shell_path.is_file():
        console.print(f"[green]OK[/] shell: {shell_path}")
    else:
        failures += 1
        error_console.print(f"[red]FAIL[/] shell not found: {shell_path}")

    with _client(model) as client:
        status = client.status()
    if not status.reachable:
        failures += 1
        error_console.print(f"[red]FAIL[/] Ollama is unavailable at {OLLAMA_HOST}: {status.error}")
    else:
        console.print(f"[green]OK[/] Ollama: {OLLAMA_HOST}")
        if model in set(status.models):
            console.print(f"[green]OK[/] model: {model}")
        else:
            failures += 1
            error_console.print(f"[red]FAIL[/] model '{model}' not found. Run: ollama pull {model}")

    if failures:
        raise typer.Exit(1)
