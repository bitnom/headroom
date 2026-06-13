"""Tests for `headroom wrap opencode` command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from headroom.cli.main import main
from headroom.cli.wrap import _resolve_proxy_port_for_upstream


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated_opencode_config_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Point XDG_CONFIG_HOME at an empty tree so tests don't read ~/.config."""
    config_home = tmp_path / "xdg-config"
    config_home.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HEADROOM_OPENCODE_PROVIDER", raising=False)
    monkeypatch.delenv("HEADROOM_OPENCODE_UPSTREAM_URL", raising=False)
    return config_home


def test_wrap_opencode_sets_provider_envs(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_opencode_config_home: Path,
) -> None:
    del isolated_opencode_config_home
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def fake_launch_tool(**kwargs):  # noqa: ANN003
        captured.update(kwargs)

    with patch("headroom.cli.wrap.shutil.which", return_value="opencode"):
        with patch("headroom.cli.wrap._launch_tool", side_effect=fake_launch_tool):
            result = runner.invoke(
                main,
                [
                    "wrap",
                    "opencode",
                    "--port",
                    "9000",
                    "--openai-api-url",
                    "https://gateway.example.com/v1",
                    "--",
                    "run",
                    "hello",
                ],
            )

    assert result.exit_code == 0, result.output
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:9000/v1"
    assert env["OPENAI_API_BASE"] == "http://127.0.0.1:9000/v1"
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9000"
    assert captured["tool_label"] == "OPENCODE"
    assert captured["agent_type"] == "opencode"
    assert captured["args"] == ("run", "hello")
    assert captured["openai_api_url"] == "https://gateway.example.com/v1"


def test_wrap_opencode_injects_provider_overlay(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_opencode_config_home: Path,
) -> None:
    del isolated_opencode_config_home
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def fake_launch_tool(**kwargs):  # noqa: ANN003
        captured.update(kwargs)

    with patch("headroom.cli.wrap.shutil.which", return_value="opencode"):
        with patch("headroom.cli.wrap._resolve_proxy_port_for_upstream", return_value=8787):
            with patch("headroom.cli.wrap._launch_tool", side_effect=fake_launch_tool):
                result = runner.invoke(
                    main,
                    [
                        "wrap",
                        "opencode",
                        "--provider",
                        "my-gateway",
                        "--openai-api-url",
                        "https://gateway.example.com/v1",
                    ],
                )

    assert result.exit_code == 0, result.output
    env = captured["env"]
    assert isinstance(env, dict)
    overlay = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert overlay["provider"]["my-gateway"]["options"]["baseURL"] == "http://127.0.0.1:8787/v1"


def test_wrap_opencode_merges_existing_config_content(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_opencode_config_home: Path,
) -> None:
    del isolated_opencode_config_home
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "OPENCODE_CONFIG_CONTENT",
        json.dumps(
            {
                "model": "my-gateway/gpt-4o",
                "provider": {
                    "my-gateway": {
                        "options": {"baseURL": "https://gateway.example.com/v1"},
                    }
                },
            }
        ),
    )
    captured: dict[str, object] = {}

    def fake_launch_tool(**kwargs):  # noqa: ANN003
        captured.update(kwargs)

    with patch("headroom.cli.wrap.shutil.which", return_value="opencode"):
        with patch("headroom.cli.wrap._resolve_proxy_port_for_upstream", return_value=8787):
            with patch("headroom.cli.wrap._launch_tool", side_effect=fake_launch_tool):
                result = runner.invoke(
                    main,
                    ["wrap", "opencode", "--provider", "my-gateway"],
                )

    assert result.exit_code == 0, result.output
    env = captured["env"]
    assert isinstance(env, dict)
    overlay = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert overlay["model"] == "my-gateway/gpt-4o"
    assert overlay["provider"]["my-gateway"]["options"]["baseURL"] == "http://127.0.0.1:8787/v1"


def test_wrap_opencode_preserves_provider_api_key_in_overlay(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_opencode_config_home: Path,
) -> None:
    del isolated_opencode_config_home
    monkeypatch.chdir(tmp_path)
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "codexeverywhere": {
                        "npm": "@ai-sdk/openai",
                        "api": "https://gateway.example.com/v1",
                        "options": {
                            "baseURL": "https://gateway.example.com/v1",
                            "apiKey": "sk-test-key",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_launch_tool(**kwargs):  # noqa: ANN003
        captured.update(kwargs)

    with patch("headroom.cli.wrap.shutil.which", return_value="opencode"):
        with patch("headroom.cli.wrap._resolve_proxy_port_for_upstream", return_value=8787):
            with patch("headroom.cli.wrap._launch_tool", side_effect=fake_launch_tool):
                result = runner.invoke(main, ["wrap", "opencode", "--provider", "codexeverywhere"])

    assert result.exit_code == 0, result.output
    env = captured["env"]
    assert isinstance(env, dict)
    overlay = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    provider = overlay["provider"]["codexeverywhere"]
    assert provider["options"]["apiKey"] == "sk-test-key"
    assert provider["options"]["baseURL"] == "http://127.0.0.1:8787/v1"
    assert provider["api"] == "http://127.0.0.1:8787/v1"
    assert env["OPENAI_API_KEY"] == "sk-test-key"


def test_wrap_opencode_propagates_codexeverywhere_context_limit(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_opencode_config_home: Path,
) -> None:
    del isolated_opencode_config_home
    monkeypatch.chdir(tmp_path)
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "model": "codexeverywhere/gpt-5.5",
                "provider": {
                    "codexeverywhere": {
                        "options": {"baseURL": "https://gateway.example.com/v1"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_launch_tool(**kwargs):  # noqa: ANN003
        captured.update(kwargs)

    with patch("headroom.cli.wrap.shutil.which", return_value="opencode"):
        with patch("headroom.cli.wrap._resolve_proxy_port_for_upstream", return_value=8787):
            with patch("headroom.cli.wrap._launch_tool", side_effect=fake_launch_tool):
                result = runner.invoke(main, ["wrap", "opencode", "--provider", "codexeverywhere"])

    assert result.exit_code == 0, result.output
    env = captured["env"]
    assert isinstance(env, dict)
    overlay = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    model = overlay["provider"]["codexeverywhere"]["models"]["gpt-5.5"]
    assert model["limit"]["context"] == 500000


def test_wrap_opencode_auto_detects_upstream_from_provider_config(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_opencode_config_home: Path,
) -> None:
    del isolated_opencode_config_home
    monkeypatch.chdir(tmp_path)
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "my-gateway": {
                        "options": {"baseURL": "https://gateway.example.com/v1"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_launch_tool(**kwargs):  # noqa: ANN003
        captured.update(kwargs)

    with patch("headroom.cli.wrap.shutil.which", return_value="opencode"):
        with patch("headroom.cli.wrap._launch_tool", side_effect=fake_launch_tool):
            result = runner.invoke(main, ["wrap", "opencode", "--provider", "my-gateway"])

    assert result.exit_code == 0, result.output
    assert captured["openai_api_url"] == "https://gateway.example.com/v1"


def test_wrap_opencode_errors_when_provider_has_no_upstream(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_opencode_config_home: Path,
) -> None:
    del isolated_opencode_config_home
    monkeypatch.chdir(tmp_path)
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")

    with patch("headroom.cli.wrap.shutil.which", return_value="opencode"):
        result = runner.invoke(main, ["wrap", "opencode", "--provider", "missing"])

    assert result.exit_code != 0
    assert "options.baseURL" in result.output


def test_resolve_proxy_port_reuses_matching_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("headroom.cli.wrap._check_proxy", lambda port: port == 8787)
    monkeypatch.setattr(
        "headroom.cli.wrap._running_proxy_openai_upstream",
        lambda port: "https://codex-everywhere.com",
    )

    resolved = _resolve_proxy_port_for_upstream(
        8787,
        openai_api_url="https://codex-everywhere.com/v1",
        no_proxy=False,
    )

    assert resolved == 8787


def test_resolve_proxy_port_picks_free_port_on_upstream_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_check_proxy(port: int) -> bool:
        return port == 8787

    def fake_running_upstream(port: int) -> str | None:
        if port == 8787:
            return "https://cli-chat-proxy.grok.com"
        return None

    monkeypatch.setattr("headroom.cli.wrap._check_proxy", fake_check_proxy)
    monkeypatch.setattr(
        "headroom.cli.wrap._running_proxy_openai_upstream",
        fake_running_upstream,
    )
    monkeypatch.setattr(
        "headroom.cli.wrap._live_proxy_clients",
        lambda port, exclude_self=True: ["grok"] if port == 8787 else [],
    )
    monkeypatch.setattr("headroom.cli.wrap._port_bind_error", lambda port: None)

    resolved = _resolve_proxy_port_for_upstream(
        8787,
        openai_api_url="https://codex-everywhere.com/v1",
        no_proxy=False,
    )

    assert resolved == 8788


def test_resolve_proxy_port_picks_free_port_for_persistent_upstream_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manifest:
        pass

    def fake_check_proxy(port: int) -> bool:
        return port == 8787

    def fake_running_upstream(port: int) -> str | None:
        if port == 8787:
            return "https://cli-chat-proxy.grok.com"
        return None

    monkeypatch.setattr("headroom.cli.wrap._check_proxy", fake_check_proxy)
    monkeypatch.setattr(
        "headroom.cli.wrap._running_proxy_openai_upstream",
        fake_running_upstream,
    )
    monkeypatch.setattr("headroom.cli.wrap._live_proxy_clients", lambda *a, **kw: [])
    monkeypatch.setattr("headroom.cli.wrap._find_persistent_manifest", lambda port: Manifest())
    monkeypatch.setattr("headroom.cli.wrap._port_bind_error", lambda port: None)

    resolved = _resolve_proxy_port_for_upstream(
        8787,
        openai_api_url="https://codex-everywhere.com/v1",
        no_proxy=False,
    )

    assert resolved == 8788


def test_resolve_proxy_port_picks_free_port_for_unknown_persistent_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Manifest:
        pass

    def fake_check_proxy(port: int) -> bool:
        return port == 8787

    monkeypatch.setattr("headroom.cli.wrap._check_proxy", fake_check_proxy)
    monkeypatch.setattr("headroom.cli.wrap._running_proxy_openai_upstream", lambda port: None)
    monkeypatch.setattr("headroom.cli.wrap._live_proxy_clients", lambda *a, **kw: [])
    monkeypatch.setattr("headroom.cli.wrap._find_persistent_manifest", lambda port: Manifest())
    monkeypatch.setattr("headroom.cli.wrap._port_bind_error", lambda port: None)

    resolved = _resolve_proxy_port_for_upstream(
        8787,
        openai_api_url="https://cli-chat-proxy.grok.com/v1",
        no_proxy=False,
    )

    assert resolved == 8788


def test_wrap_opencode_uses_dedicated_port_when_default_proxy_has_wrong_upstream(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_opencode_config_home: Path,
) -> None:
    del isolated_opencode_config_home
    monkeypatch.chdir(tmp_path)
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "codexeverywhere": {
                        "options": {"baseURL": "https://codex-everywhere.com/v1"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_launch_tool(**kwargs):  # noqa: ANN003
        captured.update(kwargs)

    with patch("headroom.cli.wrap.shutil.which", return_value="opencode"):
        with patch(
            "headroom.cli.wrap._resolve_proxy_port_for_upstream",
            return_value=8799,
        ):
            with patch("headroom.cli.wrap._launch_tool", side_effect=fake_launch_tool):
                result = runner.invoke(
                    main,
                    ["wrap", "opencode", "--provider", "codexeverywhere"],
                )

    assert result.exit_code == 0, result.output
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:8799/v1"
    assert captured["port"] == 8799
    assert captured["openai_api_url"] == "https://codex-everywhere.com/v1"


def test_wrap_opencode_missing_binary(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_opencode_config_home: Path,
) -> None:
    del isolated_opencode_config_home
    monkeypatch.chdir(tmp_path)

    with patch("headroom.cli.wrap.shutil.which", return_value=None):
        result = runner.invoke(main, ["wrap", "opencode"])

    assert result.exit_code != 0
    assert "opencode" in result.output.lower()
