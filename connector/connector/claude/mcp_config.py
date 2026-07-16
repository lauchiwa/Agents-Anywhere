"""Local MCP server config loader.

Reads `mcp.json` from the same directory as `connector.json` (or an env-var
override) and validates it against the SDK's `McpServerConfig` union. Missing
file is a legitimate "no MCP" state; malformed JSON or a bad schema raise so
the caller can decide whether to fail-soft or bubble up.

Trust boundary lives here: MCP stdio configs are effectively "run this shell
command in the user's environment", so the config must never come off the
wire — it lives on the connector host next to the identity credentials.

Security: never log `env` values, `headers`, or command `args` verbatim. Only
server name + type appear in logs, which mirrors what the SDK itself would
surface via `get_mcp_status()`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from connector.logging import logger


# Field allowlists per SDK type. Extra keys are rejected so a typo in
# `mcp.json` fails loudly rather than silently disabling a feature the user
# thought they'd configured. Kept in sync with McpStdioServerConfig /
# McpHttpServerConfig / McpSSEServerConfig in claude_agent_sdk.types.
_STDIO_KEYS = {"type", "command", "args", "env"}
_HTTP_KEYS = {"type", "url", "headers"}
_SSE_KEYS = {"type", "url", "headers"}
_TOP_LEVEL_KEYS = {"servers"}


def default_path() -> Path:
    """Resolve the mcp.json path.

    Order: `AGENT_CONNECTOR_MCP_CONFIG` env var, then the sibling of
    `connector.json` (`AGENT_CONNECTOR_CONFIG` or `~/.agent-server/`). The
    sibling location keeps MCP editing decoupled from token rotation while
    still living in the connector's private state directory.
    """
    override = os.environ.get("AGENT_CONNECTOR_MCP_CONFIG")
    if override:
        return Path(override)
    connector_cfg = os.environ.get("AGENT_CONNECTOR_CONFIG")
    if connector_cfg:
        return Path(connector_cfg).parent / "mcp.json"
    return Path.home() / ".agent-server" / "mcp.json"


def load_servers(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Read and validate `mcp.json`, returning a `{name: config}` map.

    Missing file returns an empty dict (the "no MCP" steady state).
    Malformed JSON raises `ValueError`; bad schema (unknown keys, missing
    required fields, wrong types) also raises `ValueError` with the offending
    server name so the user can fix their file. Field-level validation
    covers the SDK union (`stdio` / `http` / `sse`); the `sdk` variant is
    intentionally out of scope for this loader because it requires an
    in-process instance the JSON file can't express.
    """
    resolved = Path(path) if path is not None else default_path()
    if not resolved.is_file():
        return {}
    text = resolved.read_text(encoding="utf-8-sig")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"mcp.json at {resolved} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"mcp.json at {resolved} must be a JSON object")
    unknown_top = set(raw) - _TOP_LEVEL_KEYS
    if unknown_top:
        raise ValueError(
            f"mcp.json at {resolved} has unknown top-level keys: "
            f"{sorted(unknown_top)}"
        )
    servers_raw = raw.get("servers", {})
    if not isinstance(servers_raw, dict):
        raise ValueError(
            f"mcp.json at {resolved} 'servers' must be an object, got "
            f"{type(servers_raw).__name__}"
        )
    servers: dict[str, dict[str, Any]] = {}
    for name, cfg in servers_raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"mcp.json at {resolved} has an invalid server name: {name!r}"
            )
        if not isinstance(cfg, dict):
            raise ValueError(
                f"mcp.json at {resolved} server {name!r} must be an object"
            )
        servers[name] = _validate_server(resolved, name, cfg)
    if servers:
        # Log only name + type; never log env/headers/args. This mirrors what
        # get_mcp_status() surfaces and keeps credentials out of the log file.
        summary = ", ".join(f"{n}({s['type']})" for n, s in servers.items())
        logger.info("loaded {} MCP server(s) from {}: {}", len(servers), resolved, summary)
    return servers


def _validate_server(
    resolved: Path,
    name: str,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    # Default to stdio when `type` is omitted — matches the SDK's
    # `McpStdioServerConfig.type: NotRequired[Literal["stdio"]]` shape.
    server_type = cfg.get("type", "stdio")
    if not isinstance(server_type, str):
        raise ValueError(
            f"mcp.json at {resolved} server {name!r} 'type' must be a string"
        )
    if server_type == "stdio":
        return _validate_stdio(resolved, name, cfg)
    if server_type == "http":
        return _validate_url_config(resolved, name, cfg, allowed=_HTTP_KEYS, kind="http")
    if server_type == "sse":
        return _validate_url_config(resolved, name, cfg, allowed=_SSE_KEYS, kind="sse")
    raise ValueError(
        f"mcp.json at {resolved} server {name!r} has unsupported type "
        f"{server_type!r} (expected stdio/http/sse)"
    )


def _validate_stdio(resolved: Path, name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    unknown = set(cfg) - _STDIO_KEYS
    if unknown:
        raise ValueError(
            f"mcp.json at {resolved} stdio server {name!r} has unknown keys: "
            f"{sorted(unknown)}"
        )
    command = cfg.get("command")
    if not isinstance(command, str) or not command:
        raise ValueError(
            f"mcp.json at {resolved} stdio server {name!r} requires a "
            f"non-empty 'command' string"
        )
    validated: dict[str, Any] = {"type": "stdio", "command": command}
    args = cfg.get("args")
    if args is not None:
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError(
                f"mcp.json at {resolved} stdio server {name!r} 'args' must "
                f"be a list of strings"
            )
        validated["args"] = list(args)
    env = cfg.get("env")
    if env is not None:
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
        ):
            raise ValueError(
                f"mcp.json at {resolved} stdio server {name!r} 'env' must "
                f"be an object of string->string"
            )
        validated["env"] = dict(env)
    return validated


def _validate_url_config(
    resolved: Path,
    name: str,
    cfg: dict[str, Any],
    *,
    allowed: set[str],
    kind: str,
) -> dict[str, Any]:
    unknown = set(cfg) - allowed
    if unknown:
        raise ValueError(
            f"mcp.json at {resolved} {kind} server {name!r} has unknown keys: "
            f"{sorted(unknown)}"
        )
    url = cfg.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError(
            f"mcp.json at {resolved} {kind} server {name!r} requires a "
            f"non-empty 'url' string"
        )
    validated: dict[str, Any] = {"type": kind, "url": url}
    headers = cfg.get("headers")
    if headers is not None:
        if not isinstance(headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
        ):
            raise ValueError(
                f"mcp.json at {resolved} {kind} server {name!r} 'headers' "
                f"must be an object of string->string"
            )
        validated["headers"] = dict(headers)
    return validated


__all__ = ["default_path", "load_servers"]
