"""OpenCode config discovery and provider upstream resolution."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_CONFIG_FILENAMES = ("opencode.json", "opencode.jsonc")


def _strip_jsonc_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments without touching string contents.

    Naive ``line.split("//")`` breaks URLs like ``https://…`` — the bug that
    made real ``~/.config/opencode/opencode.json`` files unreadable.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    escaped = False
    string_quote = ""

    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == string_quote:
                in_string = False
            index += 1
            continue

        if char in {'"', "'"}:
            in_string = True
            string_quote = char
            out.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < length:
            nxt = text[index + 1]
            if nxt == "/":
                index += 2
                while index < length and text[index] not in "\n\r":
                    index += 1
                continue
            if nxt == "*":
                index += 2
                while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                    index += 1
                index = min(index + 2, length)
                continue

        out.append(char)
        index += 1

    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _parse_json_or_jsonc(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(_strip_jsonc_comments(raw))
    if not isinstance(data, dict):
        raise ValueError("expected object at config root")
    return data


def _load_config_file(path: Path) -> dict[str, Any] | None:
    raw = path.read_text(encoding="utf-8")
    try:
        data = _parse_json_or_jsonc(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Skipping unreadable OpenCode config %s: %s", path, exc)
        return None
    return data


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _global_config_paths(environ: Mapping[str, str] | None = None) -> list[Path]:
    env = environ or os.environ
    config_home = Path(env.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    root = config_home / "opencode"
    return [root / name for name in _CONFIG_FILENAMES if (root / name).is_file()]


def _project_config_paths(cwd: Path) -> list[Path]:
    """Collect project configs from git/root ancestor chain up to ``cwd``.

    Earlier directories merge first; ``cwd`` wins on conflicts — matching
    OpenCode's "walk up from cwd, later overrides earlier" behavior.
    """
    current = cwd.resolve()
    discovered: list[Path] = []
    while True:
        for name in _CONFIG_FILENAMES:
            candidate = current / name
            if candidate.is_file():
                discovered.append(candidate)
        if (current / ".git").is_dir():
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    discovered.reverse()
    return discovered


def load_merged_opencode_config(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Merge OpenCode config layers used for upstream auto-detection."""
    env = dict(environ or os.environ)
    merged: dict[str, Any] = {}

    for path in _global_config_paths(env):
        loaded = _load_config_file(path)
        if loaded is not None:
            merged = _deep_merge(merged, loaded)

    custom = env.get("OPENCODE_CONFIG", "").strip()
    if custom:
        loaded = _load_config_file(Path(custom))
        if loaded is not None:
            merged = _deep_merge(merged, loaded)

    for path in _project_config_paths(cwd or Path.cwd()):
        loaded = _load_config_file(path)
        if loaded is not None:
            merged = _deep_merge(merged, loaded)

    inline = env.get("OPENCODE_CONFIG_CONTENT", "").strip()
    if inline:
        try:
            parsed = _parse_json_or_jsonc(inline)
        except (json.JSONDecodeError, ValueError):
            parsed = {}
        merged = _deep_merge(merged, parsed)

    return merged


def extract_provider_entry(config: Mapping[str, Any], provider_id: str) -> dict[str, Any]:
    """Return a shallow copy of ``provider.<id>`` when present."""
    providers = config.get("provider")
    if not isinstance(providers, dict):
        return {}
    entry = providers.get(provider_id)
    if not isinstance(entry, dict):
        return {}
    return dict(entry)


def build_provider_proxy_overlay(
    provider_id: str,
    proxy_base: str,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Build an ``OPENCODE_CONFIG_CONTENT`` overlay that preserves credentials.

    OpenCode merges config sources key-by-key, but a sparse overlay like
    ``{"provider": {"id": {"options": {"baseURL": proxy}}}}`` can leave the
    runtime provider without ``apiKey``/``npm``/``models`` when the merge
    replaces the whole provider object. Copy the on-disk provider entry and
    only rewrite URL fields.
    """
    provider = provider_id.strip()
    entry = extract_provider_entry(
        load_merged_opencode_config(environ=environ, cwd=cwd),
        provider,
    )
    overlay_entry = dict(entry)
    options = (
        dict(entry["options"]) if isinstance(entry.get("options"), dict) else {}
    )
    options["baseURL"] = proxy_base
    overlay_entry["options"] = options
    if "api" in overlay_entry:
        overlay_entry["api"] = proxy_base
    if "baseURL" in overlay_entry:
        overlay_entry["baseURL"] = proxy_base
    return {"provider": {provider: overlay_entry}}


def extract_provider_upstream(config: Mapping[str, Any], provider_id: str) -> str | None:
    """Return a provider's configured upstream URL, if present."""
    providers = config.get("provider")
    if not isinstance(providers, dict):
        return None
    entry = providers.get(provider_id)
    if not isinstance(entry, dict):
        return None
    options = entry.get("options")
    if isinstance(options, dict):
        for key in ("baseURL", "endpoint"):
            value = options.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    api = entry.get("api")
    if isinstance(api, str) and api.strip():
        return api.strip()
    return None


def is_local_proxy_url(url: str) -> bool:
    """Return True when ``url`` already targets a loopback Headroom proxy."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def read_provider_upstream_from_config(
    provider_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> str | None:
    """Read ``provider.<id>.options.baseURL`` from merged OpenCode config."""
    provider = provider_id.strip()
    if not provider:
        return None
    upstream = extract_provider_upstream(
        load_merged_opencode_config(environ=environ, cwd=cwd),
        provider,
    )
    if upstream is None or is_local_proxy_url(upstream):
        return None
    return upstream
