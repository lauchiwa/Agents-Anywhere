# Research: Web MCP Editor

- **Query**: web-next/src/components/mcp-servers-editor.tsx — full read, McpServerConfig shape, UI flow
- **Scope**: internal
- **Date**: 2026-07-18

## Findings

### File Status: DOES NOT EXIST

`web-next/src/components/mcp-servers-editor.tsx` does not exist in the working tree. A full search of `web-next/src/` for any `mcp` references returns zero results (all `mcp` hits are in `node_modules/`).

The task spec states "the Web editor already exists" — this is likely in an unmerged branch or the file was renamed. The component was not committed to the branch `fix/android-sse-hang`.

### What Does Exist: Server-Side Type Reference

The McpServerConfig shape is fully defined server-side. See `api-types.md` for the canonical type. Summary:

**stdio**:
- `name`: string (map key, not in body)
- `type`: "stdio"
- `command`: string (required)
- `args`: string[] (optional)
- `env`: Record<string, string> (optional)

**http / sse**:
- `name`: string (map key)
- `type`: "http" | "sse"
- `url`: string (required)
- `headers`: Record<string, string> (optional)

Wire format: `{ mcpServers: { [name: string]: McpServerConfig } }`

### Expected UI Flow (inferred from server validation and web component naming)

Based on the server sanitization logic at `server/agent_server/core/runtime_config.py:687-753`, the expected UI flow is:

1. **Server list** — top-level list of named MCP servers, each collapsible or as cards
2. **Add / remove** — button to add a new empty server; trash/X button to remove an existing one
3. **Name field** — text input for the server's name (map key)
4. **Type switcher** — segmented control or dropdown: stdio | sse | http
5. **Conditional fields**:
   - stdio → show `command` text field + `args` multi-value list + `env` key-value pairs
   - sse/http → show `url` text field + `headers` key-value pairs
6. **Save** — PUT the entire `mcpServers` dict (full replacement, not patch)

### Dashboard API Methods: NOT PRESENT

`web-next/src/features/dashboard/api.ts` has no MCP methods. The web integration is also pending/unmerged.

## Caveats / Not Found

- The web component file is missing from the current branch
- Cannot confirm exact UI design choices the web editor makes
- Implementation must be inferred from server validation rules and general patterns
