"""OpenCode install-time helpers."""

from __future__ import annotations

from .runtime import OPENCODE_CONFIG_CONTENT_ENV, OPENCODE_PROVIDER_ENV, build_launch_env


def build_install_env(*, port: int, backend: str) -> dict[str, str]:
    """Build the persistent install environment for OpenCode."""
    del backend
    env, _lines = build_launch_env(port=port, environ={})
    keys = ("OPENAI_BASE_URL", "OPENAI_API_BASE", "ANTHROPIC_BASE_URL")
    install_env = {key: env[key] for key in keys if key in env}
    provider = env.get(OPENCODE_PROVIDER_ENV)
    if provider:
        install_env[OPENCODE_PROVIDER_ENV] = provider
    config_content = env.get(OPENCODE_CONFIG_CONTENT_ENV)
    if config_content:
        install_env[OPENCODE_CONFIG_CONTENT_ENV] = config_content
    return install_env
