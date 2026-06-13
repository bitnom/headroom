"""Tests for OpenCode config discovery and upstream auto-detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from headroom.providers.opencode.config import (
    build_provider_proxy_overlay,
    extract_provider_upstream,
    is_local_proxy_url,
    load_merged_opencode_config,
    read_provider_upstream_from_config,
)
from headroom.providers.opencode.runtime import resolve_upstream_url


def test_strip_jsonc_preserves_urls_while_removing_comments() -> None:
    from headroom.providers.opencode.config import _parse_json_or_jsonc

    raw = """
    {
      "$schema": "https://opencode.ai/config.json",
      "provider": {
        "codexeverywhere": {
          "api": "https://codex-everywhere.com/v1",
          "options": {
            "baseURL": "https://codex-everywhere.com/v1"
          }
        }
      },
      "mcp": {
        "playwright": {
          // inline comment after a URL-safe structure
          "enabled": true
        }
      }
    }
    """
    parsed = _parse_json_or_jsonc(raw)
    assert (
        parsed["provider"]["codexeverywhere"]["options"]["baseURL"]
        == "https://codex-everywhere.com/v1"
    )


def test_build_provider_proxy_overlay_preserves_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))
    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "codexeverywhere": {
                        "npm": "@ai-sdk/openai",
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
    overlay = build_provider_proxy_overlay(
        "codexeverywhere",
        "http://127.0.0.1:8787/v1",
        environ={},
        cwd=tmp_path,
    )
    entry = overlay["provider"]["codexeverywhere"]
    assert entry["options"]["apiKey"] == "sk-test-key"
    assert entry["options"]["baseURL"] == "http://127.0.0.1:8787/v1"
    assert entry["npm"] == "@ai-sdk/openai"


def test_build_provider_proxy_overlay_sets_codexeverywhere_context_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))
    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "model": "codexeverywhere/gpt-5.5",
                "provider": {
                    "codexeverywhere": {
                        "npm": "@ai-sdk/openai",
                        "options": {
                            "baseURL": "https://gateway.example.com/v1",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    overlay = build_provider_proxy_overlay(
        "codexeverywhere",
        "http://127.0.0.1:8787/v1",
        environ={},
        cwd=tmp_path,
    )

    model = overlay["provider"]["codexeverywhere"]["models"]["gpt-5.5"]
    assert model["limit"]["context"] == 500000


def test_extract_provider_upstream_prefers_base_url() -> None:
    config = {
        "provider": {
            "my-gateway": {
                "options": {
                    "baseURL": "https://gateway.example.com/v1",
                }
            }
        }
    }
    assert extract_provider_upstream(config, "my-gateway") == "https://gateway.example.com/v1"


def test_extract_provider_upstream_falls_back_to_api_field() -> None:
    config = {
        "provider": {
            "codexeverywhere": {
                "api": "https://codex-everywhere.com/v1",
            }
        }
    }
    assert extract_provider_upstream(config, "codexeverywhere") == "https://codex-everywhere.com/v1"


def test_extract_provider_upstream_falls_back_to_endpoint() -> None:
    config = {
        "provider": {
            "amazon-bedrock": {
                "options": {
                    "endpoint": "https://bedrock-runtime.us-east-1.amazonaws.com",
                }
            }
        }
    }
    assert (
        extract_provider_upstream(config, "amazon-bedrock")
        == "https://bedrock-runtime.us-east-1.amazonaws.com"
    )


def test_load_merged_opencode_config_project_overrides_global(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    global_dir = tmp_path / "home" / ".config" / "opencode"
    global_dir.mkdir(parents=True)
    (global_dir / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "my-gateway": {
                        "options": {"baseURL": "https://global.example.com/v1"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "my-gateway": {
                        "options": {"baseURL": "https://project.example.com/v1"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))

    merged = load_merged_opencode_config(cwd=tmp_path)
    assert extract_provider_upstream(merged, "my-gateway") == "https://project.example.com/v1"


def test_resolve_upstream_url_auto_detects_from_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))
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

    assert (
        resolve_upstream_url(provider="my-gateway", cwd=tmp_path)
        == "https://gateway.example.com/v1"
    )


def test_resolve_upstream_url_explicit_flag_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))
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

    assert (
        resolve_upstream_url(
            cli_value="https://override.example.com/v1",
            provider="my-gateway",
            cwd=tmp_path,
        )
        == "https://override.example.com/v1"
    )


def test_read_provider_upstream_ignores_loopback_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))
    (tmp_path / "opencode.json").write_text(
        json.dumps(
            {
                "provider": {
                    "my-gateway": {
                        "options": {"baseURL": "http://127.0.0.1:8787/v1"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert read_provider_upstream_from_config("my-gateway", cwd=tmp_path) is None
    assert is_local_proxy_url("http://localhost:8787/v1") is True
