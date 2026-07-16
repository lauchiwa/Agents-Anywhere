from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from connector.claude import mcp_config


def test_load_returns_empty_when_file_missing(tmp_path: Path) -> None:
    assert mcp_config.load_servers(tmp_path / "does-not-exist.json") == {}


def test_load_parses_stdio_and_http_and_sse(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    "docs": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-example"],
                        "env": {"API_KEY": "secret"},
                    },
                    "browser": {
                        "type": "http",
                        "url": "https://mcp.example.com/mcp",
                        "headers": {"Authorization": "Bearer supersecret"},
                    },
                    "stream": {
                        "type": "sse",
                        "url": "https://mcp.example.com/sse",
                    },
                }
            }
        )
    )
    servers = mcp_config.load_servers(path)
    # Exact-shape match: this is the dict handed straight to the SDK's
    # `mcp_servers` option, so drift here means the SDK sees the wrong config.
    assert servers == {
        "docs": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-example"],
            "env": {"API_KEY": "secret"},
        },
        "browser": {
            "type": "http",
            "url": "https://mcp.example.com/mcp",
            "headers": {"Authorization": "Bearer supersecret"},
        },
        "stream": {
            "type": "sse",
            "url": "https://mcp.example.com/sse",
        },
    }


def test_load_defaults_missing_type_to_stdio(tmp_path: Path) -> None:
    # SDK's McpStdioServerConfig.type is NotRequired[Literal["stdio"]], so a
    # bare `{"command": ...}` must be accepted and normalized to stdio.
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"servers": {"local": {"command": "python", "args": ["-m", "srv"]}}})
    )
    servers = mcp_config.load_servers(path)
    assert servers == {
        "local": {"type": "stdio", "command": "python", "args": ["-m", "srv"]}
    }


def test_load_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text("{not valid json")
    with pytest.raises(ValueError, match="not valid JSON"):
        mcp_config.load_servers(path)


def test_load_rejects_bad_top_level_shape(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"unexpected": {}}))
    with pytest.raises(ValueError, match="unknown top-level keys"):
        mcp_config.load_servers(path)


def test_load_rejects_bad_servers_shape(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": [1, 2, 3]}))
    with pytest.raises(ValueError, match="'servers' must be an object"):
        mcp_config.load_servers(path)


def test_load_rejects_unknown_stdio_keys(tmp_path: Path) -> None:
    # Typo in `mcp.json` should fail loudly rather than silently disable the
    # config the user thought they'd set — see comment in `_STDIO_KEYS`.
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {"servers": {"docs": {"type": "stdio", "command": "x", "arg": ["typo"]}}}
        )
    )
    with pytest.raises(ValueError, match="unknown keys"):
        mcp_config.load_servers(path)


def test_load_rejects_unsupported_type(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": {"weird": {"type": "grpc"}}}))
    with pytest.raises(ValueError, match="unsupported type"):
        mcp_config.load_servers(path)


def test_load_rejects_stdio_missing_command(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": {"docs": {"type": "stdio"}}}))
    with pytest.raises(ValueError, match="requires a non-empty 'command'"):
        mcp_config.load_servers(path)


def test_load_rejects_url_config_missing_url(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": {"http_srv": {"type": "http"}}}))
    with pytest.raises(ValueError, match="requires a non-empty 'url'"):
        mcp_config.load_servers(path)


def test_load_rejects_env_non_string_values(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {"servers": {"docs": {"type": "stdio", "command": "x", "env": {"K": 42}}}}
        )
    )
    with pytest.raises(ValueError, match="'env' must be an object of string->string"):
        mcp_config.load_servers(path)


def test_load_does_not_leak_secrets_into_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Secrets in env/headers must NEVER appear in the summary log line.

    The connector logs the loaded MCP config at INFO level so operators can
    tell "MCP is on" from a live tail. That log MUST redact env values, header
    values, and command args because MCP stdio configs commonly hold API keys
    or bearer tokens. Regression here = credentials in log aggregation.
    """
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "servers": {
                    "docs": {
                        "type": "stdio",
                        "command": "npx",
                        "args": ["-y", "some-arg-with-token=SECRET_ARG_VALUE"],
                        "env": {"API_KEY": "SECRET_ENV_VALUE"},
                    },
                    "browser": {
                        "type": "http",
                        "url": "https://mcp.example.com/mcp",
                        "headers": {"Authorization": "Bearer SECRET_HEADER_VALUE"},
                    },
                }
            }
        )
    )
    # loguru forwards to stdlib logging only when explicitly wired, so tap the
    # loguru logger directly. We record every message the loader emits and
    # assert the sensitive substrings don't appear in any of them.
    from connector.logging import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda msg: captured.append(str(msg)), level="TRACE")
    try:
        mcp_config.load_servers(path)
    finally:
        loguru_logger.remove(sink_id)
    joined = "\n".join(captured)
    assert "SECRET_ENV_VALUE" not in joined
    assert "SECRET_HEADER_VALUE" not in joined
    assert "SECRET_ARG_VALUE" not in joined
    # And the positive signal is still there so operators can see MCP is on:
    assert "docs" in joined
    assert "browser" in joined


def test_default_path_respects_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_CONNECTOR_MCP_CONFIG", "/tmp/foo/mcp.json")
    monkeypatch.delenv("AGENT_CONNECTOR_CONFIG", raising=False)
    assert mcp_config.default_path() == Path("/tmp/foo/mcp.json")


def test_default_path_falls_back_to_connector_json_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("AGENT_CONNECTOR_MCP_CONFIG", raising=False)
    monkeypatch.setenv("AGENT_CONNECTOR_CONFIG", str(tmp_path / "connector.json"))
    assert mcp_config.default_path() == tmp_path / "mcp.json"


def test_default_path_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_CONNECTOR_MCP_CONFIG", raising=False)
    monkeypatch.delenv("AGENT_CONNECTOR_CONFIG", raising=False)
    resolved = mcp_config.default_path()
    assert resolved.name == "mcp.json"
    assert resolved.parent.name == ".agent-server"
