from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from typer.core import TyperGroup

from homer import __version__
from homer.config import (
    ConfigurationError,
    LoadedSettings,
    Settings,
    is_loopback_host,
    load_settings,
)
from homer.executor import ExecutionError, execute_command
from homer.ollama import OllamaClient, OllamaError
from homer.safety import CommandValidationError, RiskLevel, inspect_command
from homer.shell_assistant import CommandProposal, ShellAssistant
from homer.writer import WritingAssistant, WritingError

_PUBLIC_COMMANDS = {"write", "doctor", "config"}
_ROOT_VALUE_OPTIONS = {"--config", "--model", "--ollama-host"}
_ROOT_EXIT_OPTIONS = {
    "--help",
    "-h",
    "--version",
    "--install-completion",
    "--show-completion",
}


def _with_default_command(args: list[str]) -> list[str]:
    """Route bare requests to the hidden shell command while preserving subcommands."""
    if not args:
        return ["_shell"]

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
    help=(
        "Turn plain-English requests into reviewed shell commands using local Ollama. "
        'Run `homer "your request"` or use a command below.'
    ),
    epilog=(
        'Examples: `homer "show the five largest files here"` · '
        '`homer --dry-run "compress Reports as tar.gz"`'
    ),
    no_args_is_help=False,
    subcommand_metavar="[REQUEST] | COMMAND",
    pretty_exceptions_enable=False,
)
config_app = typer.Typer(help="Inspect Homer's effective configuration.")
app.add_typer(config_app, name="config")

console = Console()
error_console = Console(stderr=True)


@dataclass
class AppState:
    config_path: Path | None
    model: str | None
    ollama_host: str | None
    _loaded: LoadedSettings | None = None

    def loaded(self) -> LoadedSettings:
        if self._loaded is None:
            self._loaded = load_settings(
                self.config_path,
                model=self.model,
                ollama_host=self.ollama_host,
            )
        return self._loaded


def _version(value: bool) -> None:
    if value:
        typer.echo(f"homer {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    config: Path | None = typer.Option(None, "--config", help="Path to Homer's YAML config."),
    model: str | None = typer.Option(None, "--model", help="Override the Ollama model."),
    ollama_host: str | None = typer.Option(
        None, "--ollama-host", help="Override the Ollama host URL."
    ),
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show the version."
    ),
) -> None:
    """Homer runs model requests through Ollama and keeps execution under your control."""
    del version
    ctx.obj = AppState(config, model, ollama_host)


def _settings(ctx: typer.Context) -> Settings:
    state: AppState = ctx.ensure_object(AppState)
    try:
        loaded = state.loaded()
    except ConfigurationError as exc:
        error_console.print(f"[bold red]Configuration error:[/] {exc}")
        raise typer.Exit(2) from exc
    if not is_loopback_host(loaded.values.ollama_host):
        error_console.print(
            "[bold yellow]Privacy warning:[/] the configured Ollama host is not local; "
            "prompts and document contents will leave this Mac."
        )
    return loaded.values


def _client(settings: Settings) -> OllamaClient:
    return OllamaClient(
        settings.ollama_host,
        settings.model,
        settings.timeout_seconds,
        settings.context_tokens,
    )


def _show_proposal(proposal: CommandProposal) -> None:
    console.print("\n[bold]Proposed command[/]")
    console.print(Syntax(proposal.command, "bash", word_wrap=True))
    console.print("\n[bold]Explanation[/]")
    console.print(Text(proposal.explanation))
    for warning in proposal.warnings:
        console.print("[yellow]Model warning:[/]", Text(warning))


def _process_shell_request(request: str, settings: Settings, *, dry_run: bool) -> bool:
    try:
        with _client(settings) as client:
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


def _shell_repl(settings: Settings, *, dry_run: bool) -> None:
    console.print("[bold]Homer[/] — describe a terminal task, or use [cyan]/exit[/] to leave.")
    session: PromptSession[str] = PromptSession(history=InMemoryHistory())
    while True:
        try:
            value = session.prompt("homer> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Leaving Homer.[/]")
            return
        if not value:
            continue
        if value.lower() in {"/exit", "/quit", "exit", "quit"}:
            return
        _process_shell_request(value, settings, dry_run=dry_run)


@app.command("_shell", hidden=True)
def shell(
    ctx: typer.Context,
    request: str | None = typer.Argument(
        None, help="Natural-language terminal request. Omit to start the REPL."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Generate and validate, but never execute."
    ),
) -> None:
    """Generate a shell command and require confirmation before execution."""
    settings = _settings(ctx)
    if request is None:
        _shell_repl(settings, dry_run=dry_run)
        return
    if not _process_shell_request(request, settings, dry_run=dry_run):
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
    settings: Settings,
    *,
    input_text: str | None = None,
    history: tuple[dict[str, str], ...] = (),
) -> str:
    with _client(settings) as client:
        return WritingAssistant(client, settings.style_guide, settings.context_tokens).generate(
            request, input_text=input_text, history=history
        )


@app.command()
def write(
    ctx: typer.Context,
    request: str | None = typer.Argument(
        None, help="Drafting or editing request. Omit to start the writing REPL."
    ),
    input_path: Path | None = typer.Option(None, "--input", "-i", help="UTF-8 text file to edit."),
    output_path: Path | None = typer.Option(
        None, "--output", "-o", help="Save the result instead of printing it."
    ),
    style_guide: Path | None = typer.Option(
        None, "--style-guide", help="Override the writing style guide."
    ),
    force: bool = typer.Option(False, "--force", help="Replace an existing output file."),
) -> None:
    """Draft or edit text with the optional local writing assistant."""
    settings = _settings(ctx)
    if style_guide is not None:
        settings = replace(settings, style_guide=style_guide.expanduser().resolve())
    if force and output_path is None:
        raise typer.BadParameter("--force requires --output")

    try:
        source = _read_input(input_path.expanduser().resolve()) if input_path else None
        if request is not None:
            result = _generate_writing(request, settings, input_text=source)
            if output_path:
                target = output_path.expanduser().resolve()
                _save_output(target, result, force)
                console.print(f"[green]Saved:[/] {target}")
            else:
                console.print(Text(result))
            return
    except (OllamaError, WritingError) as exc:
        error_console.print(f"[bold red]Writing failed:[/] {exc}")
        raise typer.Exit(1) from exc

    if input_path or output_path:
        raise typer.BadParameter("--input and --output require a writing request")

    console.print("[bold]Homer writing[/] — enter an instruction, or use [cyan]/exit[/] to leave.")
    session: PromptSession[str] = PromptSession(history=InMemoryHistory())
    history: list[dict[str, str]] = []
    while True:
        try:
            value = session.prompt("write> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Leaving writing mode.[/]")
            return
        if not value:
            continue
        if value.lower() in {"/exit", "/quit", "exit", "quit"}:
            return
        try:
            result = _generate_writing(value, settings, history=tuple(history))
            console.print(Text(result))
            history.extend(
                [
                    {"role": "user", "content": value},
                    {"role": "assistant", "content": result},
                ]
            )
        except (OllamaError, WritingError) as exc:
            error_console.print(f"[bold red]Writing failed:[/] {exc}")


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check zsh, Ollama, and the configured model."""
    settings = _settings(ctx)
    failures = 0

    shell_path = Path("/bin/zsh")
    if shell_path.is_file():
        console.print(f"[green]OK[/] shell: {shell_path}")
    else:
        failures += 1
        error_console.print(f"[red]FAIL[/] shell not found: {shell_path}")

    with _client(settings) as client:
        status = client.status()
    if not status.reachable:
        failures += 1
        error_console.print(
            f"[red]FAIL[/] Ollama is unavailable at {settings.ollama_host}: {status.error}"
        )
    else:
        console.print(f"[green]OK[/] Ollama: {settings.ollama_host}")
        if settings.model in set(status.models):
            console.print(f"[green]OK[/] model: {settings.model}")
        else:
            failures += 1
            error_console.print(
                f"[red]FAIL[/] model '{settings.model}' not found. "
                f"Run: ollama pull {settings.model}"
            )

    if failures:
        raise typer.Exit(1)


@config_app.command("show")
def show_config(ctx: typer.Context) -> None:
    """Show effective configuration and its source."""
    state: AppState = ctx.ensure_object(AppState)
    try:
        loaded = state.loaded()
    except ConfigurationError as exc:
        error_console.print(f"[bold red]Configuration error:[/] {exc}")
        raise typer.Exit(2) from exc
    values = loaded.values
    source = str(loaded.source) if loaded.source else "built-in defaults"
    style = str(values.style_guide) if values.style_guide else "built-in writing style"
    typer.echo(f"source: {source}")
    typer.echo(f"model: {values.model}")
    typer.echo(f"ollama_host: {values.ollama_host}")
    typer.echo(f"timeout_seconds: {values.timeout_seconds:g}")
    typer.echo(f"context_tokens: {values.context_tokens}")
    typer.echo(f"style_guide: {style}")
