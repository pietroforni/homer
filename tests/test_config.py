from pathlib import Path
from unittest.mock import patch

import pytest

from homer.config import ConfigurationError, find_config, is_loopback_host, load_settings


def test_loads_relative_paths_from_config_directory(tmp_path: Path) -> None:
    config = tmp_path / "custom.yaml"
    config.write_text(
        "model: test:7b\nstyle_guide: ./voice.md\ncontext_tokens: 4096\n",
        encoding="utf-8",
    )
    loaded = load_settings(config)

    assert loaded.values.model == "test:7b"
    assert loaded.values.style_guide == tmp_path / "voice.md"
    assert loaded.values.context_tokens == 4096
    assert loaded.source == config


def test_cli_overrides_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("model: original\n", encoding="utf-8")

    loaded = load_settings(config, model="replacement", ollama_host="http://127.0.0.1:9999/")

    assert loaded.values.model == "replacement"
    assert loaded.values.ollama_host == "http://127.0.0.1:9999"


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("modle: typo\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Unknown configuration"):
        load_settings(config)


def test_explicit_missing_config_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="does not exist"):
        find_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("http://localhost:11434", True),
        ("http://127.0.0.1:11434", True),
        ("http://[::1]:11434", True),
        ("https://example.com", False),
    ],
)
def test_loopback_detection(host: str, expected: bool) -> None:
    assert is_loopback_host(host) is expected


def test_context_limit_validation(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("context_tokens: 100\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="context_tokens"):
        load_settings(config)


@pytest.mark.parametrize("removed", ["allow_high_risk", "shell"])
def test_removed_safety_settings_are_rejected(tmp_path: Path, removed: str) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(f"{removed}: value\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Removed configuration"):
        load_settings(config)


def test_finds_user_config(tmp_path: Path) -> None:
    config = tmp_path / ".config" / "homer" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("model: home-model\n", encoding="utf-8")

    assert find_config(home=tmp_path) == config


def test_environment_config_takes_precedence(tmp_path: Path) -> None:
    config = tmp_path / "env.yaml"
    config.write_text("model: env-model\n", encoding="utf-8")

    with patch.dict("os.environ", {"HOMER_CONFIG": str(config)}):
        assert find_config(home=tmp_path) == config


def test_missing_environment_config_is_rejected(tmp_path: Path) -> None:
    with patch.dict("os.environ", {"HOMER_CONFIG": str(tmp_path / "missing")}):
        with pytest.raises(ConfigurationError, match="HOMER_CONFIG"):
            find_config(home=tmp_path)


def test_style_guide_is_optional() -> None:
    with patch("homer.config.find_config", return_value=None):
        assert load_settings().values.style_guide is None
