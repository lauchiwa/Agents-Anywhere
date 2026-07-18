# Research: Android API Methods (Sessions + Connectors)

- **Query**: Existing MCP API methods in SessionsApi.kt, SessionsController.kt, DevicesApi.kt
- **Scope**: internal
- **Date**: 2026-07-18

## Findings

### Files Found

| File Path | Description |
|---|---|
| `android/app/src/main/java/com/agentsanywhere/app/api/SessionsApi.kt` | All session API calls |
| `android/app/src/main/java/com/agentsanywhere/app/api/DevicesApi.kt` | All connector/device API calls |
| `android/app/src/main/java/com/agentsanywhere/app/feature/sessions/SessionsController.kt` | Controller wrapping SessionsApi |

### MCP Methods: NOT YET PRESENT

Neither `SessionsApi.kt`, `DevicesApi.kt`, nor `SessionsController.kt` has any MCP-related methods. The Android side needs all four methods added:

1. `SessionsApi.getSessionMcpServers(serverUrl, authToken, sessionId): Map<String, Any>` — calls `GET /sessions/{id}/mcp-servers`
2. `SessionsApi.putSessionMcpServers(serverUrl, authToken, sessionId, servers: Map<String, Any>): Map<String, Any>` — calls `PUT /sessions/{id}/mcp-servers`
3. `DevicesApi.getConnectorMcpServers(serverUrl, authToken, connectorId): Map<String, Any>` — calls `GET /connectors/{id}/mcp-servers`
4. `DevicesApi.putConnectorMcpServers(serverUrl, authToken, connectorId, servers: Map<String, Any>): Map<String, Any>` — calls `PUT /connectors/{id}/mcp-servers`

### Existing API Call Patterns (from SessionsApi.kt and DevicesApi.kt)

The `ApiClient` class provides these methods:
- `client.getJson(serverUrl, path, authorizationToken)` → `JSONObject`
- `client.postJson(serverUrl, path, body: JSONObject, authorizationToken)` → `JSONObject`
- `client.patchJson(serverUrl, path, body: JSONObject, authorizationToken)` → `JSONObject`
- `client.deleteJson(serverUrl, path, authorizationToken)` → `JSONObject`

Extension helpers used throughout: `urlEncode()`, `toMap()`, `optNullableString()`, `toObjectList {}`, `toJsonObject()`

The `toMap()` extension turns a `JSONObject?` into `Map<String, Any>`. `toJsonObject()` converts `Map<String, Any>` to `JSONObject`.

### Existing Runtime Settings Pattern (closest analog)

`DevicesApi.getDeviceAgentSettings` (line 140–151) and `patchDeviceAgentSettings` (line 153–167) show the pattern:

```kotlin
fun getDeviceAgentSettings(serverUrl, authorizationToken, deviceId, runtime): RemoteRuntimeSettings {
    return client.getJson(
        serverUrl = serverUrl,
        path = "/connectors/${deviceId.urlEncode()}/agents/${runtime.urlEncode()}/settings",
        authorizationToken = authorizationToken,
    ).toRemoteRuntimeSettings()
}
```

For MCP the response has `{ "mcpServers": { ... } }` instead of runtime settings, so parsing should extract `optJSONObject("mcpServers").toMap()`.

### SessionsController pattern

`SessionsController.kt` delegates to `SessionsApi` and wraps calls in `withContext(Dispatchers.IO) { runCatching { ... } }` returning `Result<T>`. MCP controller methods should follow the same pattern (in `DevicesController` for connector-level and in a new controller or in `SessionDetailController` for session-level).

## Caveats / Not Found

- No `ConnectorsController.kt` or `SessionDetailController.kt` dedicated file for MCP was found; the work needs to be placed in the appropriate existing controller or a new file.
