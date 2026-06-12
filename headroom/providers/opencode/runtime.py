"""Runtime helpers for OpenCode CLI integrations."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from headroom.providers.claude import proxy_base_url as claude_proxy_base_url
from headroom.providers.codex import proxy_base_url as openai_proxy_base_url
from headroom.providers.opencode.config import (
    _parse_json_or_jsonc,
    build_provider_proxy_overlay,
    read_provider_upstream_from_config,
)

OPENCODE_CONFIG_CONTENT_ENV = "OPENCODE_CONFIG_CONTENT"
OPENCODE_PROVIDER_ENV = "HEADROOM_OPENCODE_PROVIDER"
OPENCODE_UPSTREAM_ENV = "HEADROOM_OPENCODE_UPSTREAM_URL"


def proxy_base_url(port: int) -> str:
    """Return the local Headroom proxy base URL for OpenAI-compatible providers."""
    return openai_proxy_base_url(port)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into a copy of ``base``."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_launch_env(
    port: int,
    environ: Mapping[str, str] | None = None,
    *,
    provider: str | None = None,
    cwd: os.PathLike[str] | str | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Build environment variables for OpenCode through the local Headroom proxy.

    OpenCode reads provider ``baseURL`` from ``opencode.json``. To avoid
    editing on-disk config, this helper can inject a runtime override via
    ``OPENCODE_CONFIG_CONTENT`` when ``provider`` is set.
    """
    env = dict(environ or os.environ)
    openai_base = proxy_base_url(port)
    anthropic_base = claude_proxy_base_url(port)

    env["OPENAI_BASE_URL"] = openai_base
    env["OPENAI_API_BASE"] = openai_base
    env["ANTHROPIC_BASE_URL"] = anthropic_base

    display = [
        f"OPENAI_BASE_URL={openai_base}",
        f"OPENAI_API_BASE={openai_base}",
        f"ANTHROPIC_BASE_URL={anthropic_base}",
    ]

    provider_id = (provider or env.get(OPENCODE_PROVIDER_ENV) or "").strip()
    if provider_id:
        workdir = Path(cwd) if cwd is not None else Path.cwd()
        overlay = build_provider_proxy_overlay(
            provider_id,
            openai_base,
            environ=env,
            cwd=workdir,
        )
        existing_raw = env.get(OPENCODE_CONFIG_CONTENT_ENV, "").strip()
        if existing_raw:
            try:
                existing = _parse_json_or_jsonc(existing_raw)
            except (json.JSONDecodeError, ValueError):
                existing = {}
            merged = _deep_merge(existing, overlay)
        else:
            merged = overlay
        env[OPENCODE_CONFIG_CONTENT_ENV] = json.dumps(merged, separators=(",", ":"))

        provider_options = (
            overlay.get("provider", {}).get(provider_id, {}).get("options", {})
        )
        if isinstance(provider_options, dict):
            api_key = provider_options.get("apiKey")
            if isinstance(api_key, str) and api_key.strip():
                env.setdefault("OPENAI_API_KEY", api_key.strip())

        display.append(
            f"OPENCODE_CONFIG_CONTENT=provider.{provider_id}.options.baseURL={openai_base}"
        )
        if env.get("OPENAI_API_KEY"):
            display.append("OPENAI_API_KEY=<preserved from provider config>")

    return env, display


def resolve_upstream_url(
    *,
    cli_value: str | None = None,
    provider: str | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: os.PathLike[str] | str | None = None,
) -> str | None:
    """Resolve the real provider upstream URL for the Headroom proxy.

    Resolution order:
    1. Explicit CLI flag / ``HEADROOM_OPENCODE_UPSTREAM_URL`` /
       ``OPENAI_TARGET_API_URL``
    2. When ``provider`` is set, ``provider.<id>.options.baseURL`` (or
       ``endpoint``) from merged OpenCode config files
    """
    env = environ or os.environ
    for key in (cli_value, env.get(OPENCODE_UPSTREAM_ENV), env.get("OPENAI_TARGET_API_URL")):
        if isinstance(key, str) and key.strip():
            return key.strip()

    provider_id = (provider or env.get(OPENCODE_PROVIDER_ENV) or "").strip()
    if not provider_id:
        return None

    workdir = Path(cwd) if cwd is not None else Path.cwd()
    return read_provider_upstream_from_config(
        provider_id,
        environ=env,
        cwd=workdir,
    )
