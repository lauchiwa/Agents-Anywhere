package com.agentsanywhere.app.api

import org.json.JSONArray
import org.json.JSONObject

class SessionsApi(
    private val client: ApiClient = ApiClient(),
) {
    fun listSessions(
        serverUrl: String,
        authorizationToken: String,
    ): List<RemoteSession> {
        return client.getJson(
            serverUrl = serverUrl,
            path = "/sessions",
            authorizationToken = authorizationToken,
        ).optJSONArray("sessions").toObjectList { toRemoteSession() }
    }

    fun createSession(
        serverUrl: String,
        authorizationToken: String,
        connectorId: String,
        runtime: String,
        title: String?,
        cwd: String?,
    ): RemoteSession {
        val body = JSONObject().apply {
            put("connectorId", connectorId)
            put("runtime", runtime)
            title?.takeIf { it.isNotBlank() }?.let { put("title", it) }
            cwd?.takeIf { it.isNotBlank() }?.let { put("cwd", it) }
        }
        return client.postJson(
            serverUrl = serverUrl,
            path = "/sessions",
            body = body,
            authorizationToken = authorizationToken,
        ).getJSONObject("session").toRemoteSession()
    }

    fun patchSession(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
        title: String? = null,
        pinned: Boolean? = null,
        archived: Boolean? = null,
    ): RemoteSession {
        val body = JSONObject().apply {
            title?.let { put("title", it) }
            pinned?.let { put("pinned", it) }
            archived?.let { put("archived", it) }
        }
        return client.patchJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}",
            body = body,
            authorizationToken = authorizationToken,
        ).getJSONObject("session").toRemoteSession()
    }

    fun bulkArchiveSessions(
        serverUrl: String,
        authorizationToken: String,
        ids: List<String>,
        archived: Boolean,
    ): List<RemoteSession> {
        val body = JSONObject().apply {
            put("ids", JSONArray(ids))
            put("archived", archived)
        }
        return client.postJson(
            serverUrl = serverUrl,
            path = "/sessions/bulk-archive",
            body = body,
            authorizationToken = authorizationToken,
        ).optJSONArray("sessions").toObjectList { toRemoteSession() }
    }

    fun archiveAllDeviceSessions(
        serverUrl: String,
        authorizationToken: String,
        deviceId: String,
        archived: Boolean,
        scope: String,
    ): List<RemoteSession> {
        val body = JSONObject().apply {
            put("archived", archived)
            put("scope", scope)
        }
        return client.postJson(
            serverUrl = serverUrl,
            path = "/connectors/${deviceId.urlEncode()}/sessions/archive-all",
            body = body,
            authorizationToken = authorizationToken,
        ).optJSONArray("sessions").toObjectList { toRemoteSession() }
    }

    fun getRuntimeConfigSchema(
        serverUrl: String,
        authorizationToken: String,
        runtime: String,
    ): RemoteRuntimeConfigSchema {
        return client.getJson(
            serverUrl = serverUrl,
            path = "/agents/${runtime.urlEncode()}/config-schema",
            authorizationToken = authorizationToken,
        ).getJSONObject("schema").toRemoteRuntimeConfigSchema()
    }

    fun getSessionRuntimeSettings(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
    ): RemoteRuntimeSettings {
        return client.getJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/runtime-settings",
            authorizationToken = authorizationToken,
        ).toRemoteRuntimeSettings()
    }

    fun patchSessionRuntimeSettings(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
        settings: Map<String, Any?>,
    ): RemoteRuntimeSettings {
        val body = JSONObject().put("settings", settings.toJsonObject())
        return client.patchJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/runtime-settings",
            body = body,
            authorizationToken = authorizationToken,
        ).toRemoteRuntimeSettings()
    }

    fun getSessionState(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
        afterSeq: Int = 0,
        beforeOrderSeq: Int? = null,
        mode: String = "since",
        limit: Int = 500,
    ): RemoteSessionState {
        val query = buildList {
            add("mode=${mode.urlEncode()}")
            add("limit=$limit")
            when (mode) {
                "before" -> beforeOrderSeq?.let { add("beforeOrderSeq=$it") }
                "latest" -> Unit
                else -> add("afterSeq=$afterSeq")
            }
        }.joinToString("&")
        return client.getJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/state?$query",
            authorizationToken = authorizationToken,
        ).toRemoteSessionState()
    }

    fun streamSessionEvents(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
        onOpen: () -> Unit = {},
        onStart: (okhttp3.Call) -> Unit = {},
        onEvent: (RemoteSessionEvent) -> Unit,
    ) {
        client.streamSse(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/events?token=${authorizationToken.urlEncode()}",
            onOpen = onOpen,
            onStart = onStart,
        ) { event ->
            onEvent(event.toRemoteSessionEvent())
        }
    }

    fun sendSessionMessage(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
        content: String,
        clientMessageId: String,
        attachments: List<RemoteUploadedAttachment> = emptyList(),
    ): RemoteRpcResponse {
        val body = JSONObject()
            .put("content", content)
            .put("clientMessageId", clientMessageId)
        if (attachments.isNotEmpty()) {
            body.put(
                "attachments",
                JSONArray(attachments.map { JSONObject().put("fileId", it.fileId) }),
            )
        }
        return client.postJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/messages",
            body = body,
            authorizationToken = authorizationToken,
        ).toRemoteRpcResponse()
    }

    fun uploadSessionAttachments(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
        files: List<UploadFilePart>,
    ): List<RemoteUploadedAttachment> {
        return client.postMultipart(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/attachments",
            files = files,
            authorizationToken = authorizationToken,
        ).optJSONArray("attachments").toObjectList { toRemoteUploadedAttachment() }
    }

    fun attachmentOpenUrl(
        serverUrl: String,
        sessionId: String,
        fileId: String,
    ): String {
        return "${serverUrl.trimEnd('/')}/sessions/${sessionId.urlEncode()}/attachments/${fileId.urlEncode()}/open"
    }

    fun forkSession(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
    ): RemoteRpcResponse {
        return client.postJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/fork",
            body = JSONObject(),
            authorizationToken = authorizationToken,
        ).toRemoteRpcResponse()
    }

    fun deleteSession(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
    ): RemoteRpcResponse {
        return client.postJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/delete",
            body = JSONObject(),
            authorizationToken = authorizationToken,
        ).toRemoteRpcResponse()
    }

    fun tagSession(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
        tag: String?,
    ): RemoteRpcResponse {
        val body = JSONObject()
        if (tag != null) body.put("tag", tag) else body.put("tag", JSONObject.NULL)
        return client.postJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/tag",
            body = body,
            authorizationToken = authorizationToken,
        ).toRemoteRpcResponse()
    }

    fun interruptSession(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
    ): RemoteRpcResponse {
        return client.postJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/interrupt",
            body = JSONObject(),
            authorizationToken = authorizationToken,
        ).toRemoteRpcResponse()
    }

    fun enableTakeover(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
    ): RemoteSession {
        return client.postJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/takeover",
            body = JSONObject(),
            authorizationToken = authorizationToken,
        ).getJSONObject("session").toRemoteSession()
    }

    fun disableTakeover(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
    ): RemoteSession {
        return client.deleteJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/takeover",
            authorizationToken = authorizationToken,
        ).getJSONObject("session").toRemoteSession()
    }

    fun resolveApproval(
        serverUrl: String,
        authorizationToken: String,
        approvalId: String,
        status: String,
        selections: List<ApprovalSelectionInput> = emptyList(),
    ): RemoteRpcResponse {
        val body = JSONObject().put("status", status)
        if (selections.isNotEmpty()) {
            // AskUserQuestion answers: [{"question": str, "labels": [str, ...]}, ...].
            body.put(
                "selections",
                JSONArray().apply {
                    selections.forEach { selection ->
                        put(
                            JSONObject()
                                .put("question", selection.question)
                                .put("labels", JSONArray(selection.labels)),
                        )
                    }
                },
            )
        }
        return client.postJson(
            serverUrl = serverUrl,
            path = "/approvals/${approvalId.urlEncode()}/resolve",
            body = body,
            authorizationToken = authorizationToken,
        ).toRemoteRpcResponse()
    }

    private fun JSONObject.toRemoteSession(): RemoteSession {
        return RemoteSession(
            id = getString("id"),
            connectorId = getString("connectorId"),
            connectorStatus = optString("connectorStatus", "offline"),
            runtime = optString("runtime", "codex"),
            externalSessionId = optNullableString("externalSessionId"),
            title = optNullableString("title"),
            cwd = optNullableString("cwd"),
            status = optString("status", "idle"),
            takeover = optBoolean("takeover", false),
            pinned = optBoolean("pinned", false),
            archived = optBoolean("archived", false),
            unread = optBoolean("unread", false),
            lastSyncedAt = optNullableString("lastSyncedAt"),
            sourceObservedAt = optNullableString("sourceObservedAt"),
            lastActivityAt = optNullableString("lastActivityAt"),
            lastItemAt = optNullableString("lastItemAt"),
            sortAt = optNullableString("sortAt"),
            updatedSeq = optInt("updatedSeq", 0),
            runtimeSettings = optJSONObject("runtimeSettings").toMap(),
            runtimeSettingsOverride = optJSONObject("runtimeSettingsOverride").toMap(),
            contextUsage = optJSONObject("contextUsage")?.toRemoteContextUsage(),
            tag = optNullableString("tag"),
        )
    }

    private fun JSONObject.toRemoteSessionState(): RemoteSessionState {
        return RemoteSessionState(
            session = getJSONObject("session").toRemoteSession(),
            items = optJSONArray("items").toObjectList { toRemoteTimelineItem() },
            approvals = optJSONArray("approvals").toObjectList { toRemoteApproval() },
            nextSeq = optInt("nextSeq", 0),
            hasMore = optBoolean("hasMore", false),
        )
    }

    private fun JSONObject.toRemoteRuntimeConfigSchema(): RemoteRuntimeConfigSchema {
        return RemoteRuntimeConfigSchema(
            runtime = optString("runtime", ""),
            schemaVersion = optInt("schemaVersion", 0),
            fields = optJSONArray("fields").toObjectList { toRemoteRuntimeConfigField() },
        )
    }

    private fun JSONObject.toRemoteRuntimeConfigField(): RemoteRuntimeConfigField {
        return RemoteRuntimeConfigField(
            key = optString("key", ""),
            label = optString("label", ""),
            type = optString("type", "string"),
            description = optNullableString("description"),
            options = optJSONArray("options").toObjectList { toRemoteRuntimeConfigOption() },
            visibleWhen = optJSONObject("visibleWhen").toMap(),
            allowSessionOverride = optBoolean("allowSessionOverride", false),
            hidden = optBoolean("hidden", false),
        )
    }

    private fun JSONObject.toRemoteRuntimeConfigOption(): RemoteRuntimeConfigOption {
        return RemoteRuntimeConfigOption(
            value = opt("value")?.toString().orEmpty(),
            label = optString("label", ""),
            description = optNullableString("description"),
            efforts = if (has("efforts") && !isNull("efforts")) {
                optJSONArray("efforts").toObjectList { toRemoteRuntimeConfigOption() }
            } else {
                null
            },
        )
    }

    private fun JSONObject.toRemoteRuntimeSettings(): RemoteRuntimeSettings {
        return RemoteRuntimeSettings(
            runtime = optString("runtime", ""),
            settings = (optJSONObject("runtimeSettings") ?: optJSONObject("settings")).toMap(),
            runtimeSettingsOverride = optJSONObject("runtimeSettingsOverride").toMap(),
            schemaVersion = optInt("schemaVersion", 0),
        )
    }

    private fun JSONObject.toRemoteTimelineItem(): RemoteTimelineItem {
        val content = optJSONObject("content") ?: JSONObject()
        return RemoteTimelineItem(
            id = getString("id"),
            sessionId = optString("sessionId", ""),
            turnId = optNullableString("turnId"),
            type = optString("type", "message"),
            status = optString("status", "done"),
            role = optNullableString("role"),
            text = content.optNullableString("text")
                ?: content.optNullableString("message")
                ?: content.optNullableString("description")
                ?: "",
            content = content,
            source = optJSONObject("source") ?: JSONObject(),
            orderSeq = optInt("orderSeq", 0),
            updatedSeq = optInt("updatedSeq", 0),
            createdAt = optString("createdAt", ""),
            completedAt = optNullableString("completedAt"),
            parentItemId = optNullableString("parentItemId"),
        )
    }

    private fun JSONObject.toRemoteApproval(): RemoteApproval {
        return RemoteApproval(
            id = getString("id"),
            sessionId = optString("sessionId", ""),
            turnId = optNullableString("turnId"),
            status = optString("status", "pending"),
            kind = optString("kind", "unknown"),
            targetItemId = optNullableString("targetItemId"),
            title = optString("title", "Permission request"),
            description = optNullableString("description"),
            choices = optJSONArray("choices").toStringList(),
            questions = optJSONObject("payload")
                ?.optJSONObject("input")
                ?.optJSONArray("questions")
                .toObjectList { toRemoteApprovalQuestion() },
            updatedSeq = optInt("updatedSeq", 0),
            createdAt = optString("createdAt", ""),
        )
    }

    private fun JSONObject.toRemoteApprovalQuestion(): RemoteApprovalQuestion {
        return RemoteApprovalQuestion(
            header = optNullableString("header"),
            question = optString("question", ""),
            multiSelect = optBoolean("multiSelect", false),
            options = optJSONArray("options").toObjectList { toRemoteApprovalQuestionOption() },
        )
    }

    private fun JSONObject.toRemoteApprovalQuestionOption(): RemoteApprovalQuestionOption {
        return RemoteApprovalQuestionOption(
            label = optString("label", ""),
            description = optNullableString("description"),
        )
    }

    private fun JSONObject.toRemoteSessionEvent(): RemoteSessionEvent {
        return RemoteSessionEvent(
            sessionId = optString("sessionId", ""),
            items = optJSONArray("items").toObjectList { toRemoteTimelineItem() },
            approvals = if (has("approvals")) {
                optJSONArray("approvals").toObjectList { toRemoteApproval() }
            } else {
                null
            },
            session = optJSONObject("session")?.toRemoteSession(),
            nextSeq = optInt("nextSeq", 0),
            refetch = optBoolean("refetch", false),
        )
    }

    private fun JSONObject.toRemoteRpcResponse(): RemoteRpcResponse {
        val result = optJSONObject("result")
        return RemoteRpcResponse(
            ok = optBoolean("ok", false),
            turnId = result?.optNullableString("turnId"),
        )
    }

    private fun JSONObject.toRemoteUploadedAttachment(): RemoteUploadedAttachment {
        return RemoteUploadedAttachment(
            fileId = getString("fileId"),
            name = optString("name", "attachment"),
            mediaType = optString("mediaType", ""),
            size = optLong("size", 0L),
        )
    }

    fun getSessionMcpServers(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
    ): Map<String, McpServerConfig> {
        val response = client.getJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/mcp-servers",
            authorizationToken = authorizationToken,
        )
        return response.optJSONObject("mcpServers")?.toMcpServersMap() ?: emptyMap()
    }

    fun putSessionMcpServers(
        serverUrl: String,
        authorizationToken: String,
        sessionId: String,
        servers: Map<String, McpServerConfig>,
    ): Map<String, McpServerConfig> {
        val body = JSONObject().put("mcpServers", servers.toMcpServersJsonObject())
        val response = client.putJson(
            serverUrl = serverUrl,
            path = "/sessions/${sessionId.urlEncode()}/mcp-servers",
            body = body,
            authorizationToken = authorizationToken,
        )
        return response.optJSONObject("mcpServers")?.toMcpServersMap() ?: emptyMap()
    }
}
