from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from homer.ollama import OllamaClient, OllamaResponseError

SHELL_SYSTEM_PROMPT = """You translate a user's terminal request into one conservative shell
command for macOS with the standard BSD userland. Do not use GNU-only options such as long flags
for du, find -printf, grep -P, sed -r, readlink -f, or xargs -r. Prefer simple commands that ship
with macOS, quote paths safely, never use sudo, and do not invent paths.

Return JSON only, with exactly these fields:
{"command": "single-line command", "explanation": "plain-language explanation",
"warnings": ["warning"]}

Warnings must describe a concrete risk or limitation of the proposed command. Use an empty list
when there is no concrete warning; do not speculate about missing privileges or command behavior.

For example, a request for the five largest items in the current directory can use
`du -sh ./* | sort -hr | head -n 5`. Never include Markdown fences. The application will validate
the command and ask the user before execution."""


@dataclass(frozen=True)
class CommandProposal:
    command: str
    explanation: str
    warnings: tuple[str, ...]


def _proposal_from_json(content: str) -> CommandProposal:
    try:
        value: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise OllamaResponseError("The model did not return valid command JSON.") from exc
    if not isinstance(value, dict) or set(value) != {"command", "explanation", "warnings"}:
        raise OllamaResponseError(
            "The model response must contain only command, explanation, and warnings."
        )
    command = value["command"]
    explanation = value["explanation"]
    warnings = value["warnings"]
    if not isinstance(command, str) or not command.strip():
        raise OllamaResponseError("The model returned an empty or invalid command.")
    if not isinstance(explanation, str) or not explanation.strip():
        raise OllamaResponseError("The model returned an invalid explanation.")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise OllamaResponseError("The model returned invalid warnings.")
    return CommandProposal(command.strip(), explanation.strip(), tuple(warnings))


class ShellAssistant:
    def __init__(self, client: OllamaClient) -> None:
        self.client = client

    def propose(self, request: str) -> CommandProposal:
        if not request.strip():
            raise ValueError("The shell request cannot be empty.")
        content = self.client.chat(
            [
                {"role": "system", "content": SHELL_SYSTEM_PROMPT},
                {"role": "user", "content": request.strip()},
            ],
            json_mode=True,
        )
        return _proposal_from_json(content)
