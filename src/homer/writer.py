from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib.resources import files
from pathlib import Path

from homer.ollama import OllamaClient


class WritingError(ValueError):
    pass


class WritingAssistant:
    def __init__(self, client: OllamaClient, style_guide: Path | None, context_tokens: int) -> None:
        self.client = client
        self.style_guide = style_guide
        self.context_tokens = context_tokens

    def _read_style(self) -> str:
        try:
            if self.style_guide is None:
                content = (
                    files("homer")
                    .joinpath("resources/default_style_guide.md")
                    .read_text(encoding="utf-8")
                    .strip()
                )
            else:
                content = self.style_guide.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            source = self.style_guide or "the built-in style guide"
            raise WritingError(f"Could not read style guide {source}: {exc}") from exc
        if not content:
            source = self.style_guide or "the built-in style guide"
            raise WritingError(f"Style guide is empty: {source}")
        return content

    def generate(
        self,
        request: str,
        *,
        input_text: str | None = None,
        history: Sequence[Mapping[str, str]] = (),
    ) -> str:
        if not request.strip():
            raise WritingError("The writing request cannot be empty.")
        style = self._read_style()
        source = input_text or ""
        approximate_limit = self.context_tokens * 4
        history_size = sum(len(item.get("content", "")) for item in history)
        if len(style) + len(request) + len(source) + history_size > int(approximate_limit * 0.8):
            raise WritingError(
                "The style guide and input are too large for the configured context window. "
                "Shorten the input or increase context_tokens."
            )

        system = (
            "You are a private local writing assistant. Follow the supplied style guide. "
            "Return only the requested finished text, without commentary about the task.\n\n"
            f"STYLE GUIDE:\n{style}"
        )
        user = request.strip()
        if input_text is not None:
            user += f"\n\nTEXT TO EDIT:\n{input_text}"
        messages = [
            {"role": "system", "content": system},
            *history,
            {"role": "user", "content": user},
        ]
        return self.client.chat(messages)
