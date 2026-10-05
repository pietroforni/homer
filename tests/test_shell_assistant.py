import pytest

from homer.ollama import OllamaResponseError
from homer.shell_assistant import ShellAssistant, _proposal_from_json


class FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.json_mode = False
        self.messages: object = None

    def chat(self, messages: object, *, json_mode: bool = False) -> str:
        self.json_mode = json_mode
        self.messages = messages
        return self.response


def test_proposal_uses_json_mode() -> None:
    client = FakeClient('{"command":"pwd","explanation":"Print the directory.","warnings":[]}')
    proposal = ShellAssistant(client).propose("where am I")  # type: ignore[arg-type]

    assert client.json_mode
    assert proposal.command == "pwd"
    assert "standard BSD userland" in client.messages[0]["content"]  # type: ignore[index]
    assert "Use an empty list" in client.messages[0]["content"]  # type: ignore[index]


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{"command":"pwd","explanation":"why"}',
        '{"command":"","explanation":"why","warnings":[]}',
        '{"command":"pwd","explanation":"why","warnings":"none"}',
        '{"command":"pwd","explanation":"why","warnings":[],"extra":true}',
    ],
)
def test_malformed_proposals_are_rejected(response: str) -> None:
    with pytest.raises(OllamaResponseError):
        _proposal_from_json(response)
