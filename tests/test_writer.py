from pathlib import Path

import pytest

from homer.writer import WritingAssistant, WritingError


class FakeClient:
    def __init__(self, response: str = "Finished text") -> None:
        self.response = response
        self.messages: object = None

    def chat(self, messages: object, *, json_mode: bool = False) -> str:
        self.messages = messages
        return self.response


def test_writer_includes_style_and_input(tmp_path: Path) -> None:
    style = tmp_path / "style.md"
    style.write_text("Use short sentences.", encoding="utf-8")
    client = FakeClient()

    result = WritingAssistant(client, style, 8192).generate(  # type: ignore[arg-type]
        "Improve this", input_text="A long sentence."
    )

    assert result == "Finished text"
    assert "Use short sentences" in client.messages[0]["content"]  # type: ignore[index]
    assert "A long sentence" in client.messages[-1]["content"]  # type: ignore[index]


def test_missing_style_guide_is_rejected(tmp_path: Path) -> None:
    writer = WritingAssistant(FakeClient(), tmp_path / "missing.md", 8192)  # type: ignore[arg-type]
    with pytest.raises(WritingError, match="Could not read style guide"):
        writer.generate("Draft something")


def test_packaged_style_guide_is_used_by_default() -> None:
    client = FakeClient()

    WritingAssistant(client, None, 8192).generate("Draft something")  # type: ignore[arg-type]

    assert "Lead with the main idea" in client.messages[0]["content"]  # type: ignore[index]


def test_oversized_input_is_rejected(tmp_path: Path) -> None:
    style = tmp_path / "style.md"
    style.write_text("Clear.", encoding="utf-8")
    writer = WritingAssistant(FakeClient(), style, 1024)  # type: ignore[arg-type]

    with pytest.raises(WritingError, match="too large"):
        writer.generate("Edit", input_text="x" * 4000)


def test_oversized_repl_history_is_rejected(tmp_path: Path) -> None:
    style = tmp_path / "style.md"
    style.write_text("Clear.", encoding="utf-8")
    writer = WritingAssistant(FakeClient(), style, 1024)  # type: ignore[arg-type]

    with pytest.raises(WritingError, match="too large"):
        writer.generate("Continue", history=({"role": "user", "content": "x" * 4000},))
