# Research: Android String Resources

- **Query**: Existing mcp_* keys and naming convention in strings.xml
- **Scope**: internal
- **Date**: 2026-07-18

## Findings

### File Found

| File Path | Description |
|---|---|
| `android/app/src/main/res/values/strings.xml` | All 455-line string resource file |

### MCP-Related Keys: NONE EXIST

Searching the full `strings.xml` for `mcp` returns zero matches. The only MCP reference is in `session_mcp_arguments`, `session_mcp_result`, `session_mcp_error` — these are for displaying MCP tool call output in the chat thread, not for the editor.

Existing MCP display strings (lines 360-362):
```xml
<string name="session_mcp_arguments">arguments</string>
<string name="session_mcp_result">result</string>
<string name="session_mcp_error">error</string>
```

### Naming Convention

The pattern is `<screen>_<description>`. Key sections:
- `common_*` — shared labels (cancel, close, save, done, delete, add, etc.)
- `auth_*`, `oauth_*`, `qr_*` — auth screens
- `home_*` — home screen
- `devices_*` — devices list
- `add_agent_*` — add agent sheet
- `agent_settings_*` — DeviceAgentSettingsSheet strings
- `device_detail_*` — device detail screen
- `device_setup_*`, `device_actions_*`, `device_confirm_*` — device sub-flows
- `session_*` — session screens
- `session_runtime_*`, `runtime_*` — runtime settings sheet
- `new_session_*` — new session flow
- `files_*`, `profile_*` — other screens

### Common Strings Reusable for MCP Editor

Already available without adding new strings:
- `common_cancel`, `common_save`, `common_saving`, `common_done`, `common_close`
- `common_delete`, `common_add` (missing — not present, need `mcp_add_server` or similar)
- `common_ok`, `common_back`
- `device_detail_agent_settings` ("Agent settings") — existing example of settings label

### New Strings Needed

Following the convention, new keys for the MCP editor would be:
```xml
<!-- Connector-level MCP -->
<string name="connector_mcp_title">MCP Servers</string>
<string name="connector_mcp_load_failed">Could not load MCP servers.</string>
<string name="connector_mcp_save_failed">Could not save MCP servers.</string>
<string name="connector_mcp_add_server">Add server</string>
<string name="connector_mcp_no_servers">No MCP servers configured.</string>
<string name="connector_mcp_server_name">Server name</string>
<string name="connector_mcp_server_type">Type</string>
<string name="connector_mcp_command">Command</string>
<string name="connector_mcp_args">Arguments (one per line)</string>
<string name="connector_mcp_url">URL</string>
<string name="connector_mcp_env_key">Key</string>
<string name="connector_mcp_env_value">Value</string>
<string name="connector_mcp_headers">Headers</string>
<string name="connector_mcp_env">Environment Variables</string>
<string name="connector_mcp_add_env">Add variable</string>
<string name="connector_mcp_add_header">Add header</string>

<!-- Session-level MCP -->
<string name="session_mcp_servers_title">MCP Servers</string>
<string name="session_mcp_load_failed">Could not load MCP servers.</string>
<string name="session_mcp_save_failed">Could not save MCP servers.</string>
```

## Caveats / Not Found

- `common_add` does not exist (only `common_save`, `common_done` etc.) — "Add server" needs a new string
- The exact names should be confirmed when implementing to stay consistent with the team's conventions
