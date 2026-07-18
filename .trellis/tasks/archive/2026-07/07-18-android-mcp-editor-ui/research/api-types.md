# Research: API Types and Shape

- **Query**: McpServerConfig definition, API request/response models, getMcpServers/putMcpServers methods
- **Scope**: internal
- **Date**: 2026-07-18

## Findings

### McpServerConfig Shape (from server/agent_server/core/runtime_config.py:687-753)

The data model is a dict keyed by server name. There is no shared TypeScript `McpServerConfig` in web-next — the web component does not yet exist. The canonical shape is defined server-side:

**stdio type** (fields: type, command, args, env):
```
{
  "type": "stdio",
  "command": "<non-empty string>",
  "args": ["<string>", ...],          // optional
  "env": { "<key>": "<value>", ... }  // optional, string→string pairs
}
```

**http / sse type** (fields: type, url, headers):
```
{
  "type": "http" | "sse",
  "url": "<non-empty string>",
  "headers": { "<key>": "<value>", ... }  // optional, string→string pairs
}
```

The `"sdk"` type is rejected by the API. Invalid/unknown keys are rejected.

### Wire Format

- GET/PUT `/api/connectors/{id}/mcp-servers` — connector-level
- GET/PUT `/api/sessions/{id}/mcp-servers` — session-level
- Request body: `{ "mcpServers": { "<name>": { ... } } }`
- Response:     `{ "mcpServers": { "<name>": { ... } } }`

Models at `server/agent_server/core/models.py:988-992`:
```python
class McpServersPutBody(BaseModel):
    mcpServers: dict[str, Any]

class McpServersResponse(BaseModel):
    mcpServers: dict[str, Any]
```

### Backend API Endpoints

| File | Line | Endpoint |
|---|---|---|
| `server/agent_server/api/connectors.py` | 338 | `GET /{connector_id}/mcp-servers` |
| `server/agent_server/api/connectors.py` | 354 | `PUT /{connector_id}/mcp-servers` |
| `server/agent_server/api/sessions.py` | 653 | `GET /{session_id}/mcp-servers` |
| `server/agent_server/api/sessions.py` | 667 | `PUT /{session_id}/mcp-servers` |

### No Web TypeScript Types Yet

Searching `web-next/src/**` for `McpServerConfig`, `mcpServer`, `mcp-server` returns zero matches. The web editor and web API types are not yet committed to the repo. The task calls for implementing them in Android fresh.

### Database Storage

- `connectors.mcp_servers_json TEXT` — connector-level blob
- `sessions.mcp_servers_json TEXT` — session-level blob
- Session wins on merge: `{**(connector or {}), **(session or {})}`

## Caveats / Not Found

- `web-next/src/components/mcp-servers-editor.tsx` does not exist (task spec says "already exists" but is not in the tree)
- `web-next/src/features/dashboard/types.ts` has no McpServerConfig definition
- `web-next/src/features/dashboard/api.ts` has no getMcpServers/putMcpServers methods
- The web editor is likely in a branch not yet merged
