from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx


class OllamaError(RuntimeError):
    """Base error for Ollama communication."""


class OllamaConnectionError(OllamaError):
    pass


class ModelUnavailableError(OllamaError):
    pass


class OllamaResponseError(OllamaError):
    pass


@dataclass(frozen=True)
class OllamaStatus:
    reachable: bool
    models: tuple[str, ...] = ()
    error: str | None = None


class OllamaClient:
    def __init__(
        self,
        host: str,
        model: str,
        timeout_seconds: float = 60.0,
        context_tokens: int = 8192,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.context_tokens = context_tokens
        self._client = httpx.Client(
            base_url=self.host,
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self._client.request(method, path, **kwargs)
                if response.status_code >= 500 and attempt == 0:
                    continue
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt == 0:
                    continue
        raise OllamaConnectionError(
            f"Could not connect to Ollama at {self.host}: {last_error}"
        ) from last_error

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        json_mode: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
            "options": {"num_ctx": self.context_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        response = self._request("POST", "/api/chat", json=payload)

        if response.status_code == 404:
            raise ModelUnavailableError(
                f"Model '{self.model}' is not available. Run: ollama pull {self.model}"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OllamaResponseError(
                f"Ollama returned HTTP {response.status_code}: {response.text[:300]}"
            ) from exc

        try:
            data = response.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OllamaResponseError("Ollama returned a malformed chat response.") from exc
        if not isinstance(content, str) or not content.strip():
            raise OllamaResponseError("Ollama returned an empty response.")
        return content.strip()

    def status(self) -> OllamaStatus:
        try:
            response = self._request("GET", "/api/tags")
            response.raise_for_status()
            data = response.json()
            models = tuple(
                item["name"]
                for item in data.get("models", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            )
            return OllamaStatus(True, models)
        except (OllamaError, httpx.HTTPError, ValueError, TypeError) as exc:
            return OllamaStatus(False, error=str(exc))
