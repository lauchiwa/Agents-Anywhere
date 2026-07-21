package com.agentsanywhere.app.feature.sessiondetail

import com.agentsanywhere.app.api.ApiException
import com.agentsanywhere.app.api.ApprovalSelectionInput
import com.agentsanywhere.app.api.RemoteApproval
import com.agentsanywhere.app.api.RemoteRuntimeConfigField
import com.agentsanywhere.app.api.RemoteRuntimeConfigOption
import com.agentsanywhere.app.api.RemoteRuntimeConfigSchema
import com.agentsanywhere.app.api.RemoteRuntimeSettings
import com.agentsanywhere.app.api.RemoteSession
import com.agentsanywhere.app.api.toContextUsage
import com.agentsanywhere.app.api.toRateLimit
import com.agentsanywhere.app.api.toSessionMeta
import com.agentsanywhere.app.api.toStringList
import com.agentsanywhere.app.api.RemoteSessionEvent
import com.agentsanywhere.app.api.RemoteTimelineItem
import com.agentsanywhere.app.api.RemoteUploadedAttachment
import com.agentsanywhere.app.api.SessionsApi
import com.agentsanywhere.app.api.UploadFilePart
import com.agentsanywhere.app.feature.auth.AuthSessionStore
import com.agentsanywhere.app.feature.sessions.runtimeLabel
import com.agentsanywhere.app.model.AgentDevice
import com.agentsanywhere.app.model.AgentSession
import com.agentsanywhere.app.model.SessionStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.max

private const val INITIAL_TIMELINE_LIMIT = 100
private const val TIMELINE_PAGE_LIMIT = 100

// SSE reconnect backoff. A fast-failing stream (server briefly down, transient
// network drop) must not reconnect in a tight ~1s loop — that was what
// exhausted the client's connection pool and froze the UI. Start small so a
// healthy reconnect is near-instant, then grow to a ceiling. The backoff resets
// to the minimum every time the stream successfully connects (onOpen).
private const val SSE_RECONNECT_MIN_MS = 1_000L
private const val SSE_RECONNECT_MAX_MS = 30_000L

class SessionDetailController(
    private val sessionsApi: SessionsApi,
    private val sessionStore: AuthSessionStore,
) {
    private val optimisticLock = Any()
    private val optimisticMessagesBySession = mutableMapOf<String, List<TimelineMessage>>()

    suspend fun load(
        sessionId: String,
        devices: List<AgentDevice>,
        currentState: SessionDetailState? = null,
    ): Result<SessionDetailState> {
        return withContext(Dispatchers.IO) {
            runCatching {
                val auth = authSession()
                val page = sessionsApi.getSessionState(
                    serverUrl = auth.serverUrl,
                    authorizationToken = auth.accessToken,
                    sessionId = sessionId,
                    mode = "latest",
                    limit = INITIAL_TIMELINE_LIMIT,
                )
                val items = page.items
                val realMessages = items.flatMap { it.toTimelineMessages() }
                val messages = mergeOptimistic(
                    sessionId = sessionId,
                    realMessages = realMessages,
                    currentMessages = currentState?.messages.orEmpty(),
                )
                SessionDetailState(
                    session = page.session.toAgentSession(devices.associateBy { it.id }),
                    messages = messages,
                    approvals = page.approvals.map { it.toTimelineApproval() },
                    nextSeq = page.nextSeq,
                    hasMore = page.hasMore,
                    isLoading = false,
                    loadingOlder = false,
                    errorMessage = null,
                    actionError = currentState?.actionError,
                    sseConnected = currentState?.sseConnected ?: false,
                    takeoverInFlight = currentState?.takeoverInFlight ?: false,
                    sending = currentState?.sending ?: messages.hasPendingOptimisticSend(),
                    interrupting = currentState?.interrupting ?: false,
                )
            }.recoverCatching { error ->
                if (error is ApiException) throw error
                throw IllegalStateException(error.message ?: "Could not load messages.", error)
            }
        }
    }

    suspend fun loadOlder(
        sessionId: String,
        beforeOrderSeq: Int,
        devices: List<AgentDevice>,
    ): Result<SessionDetailState> {
        return withContext(Dispatchers.IO) {
            runCatching {
                val auth = authSession()
                val page = sessionsApi.getSessionState(
                    serverUrl = auth.serverUrl,
                    authorizationToken = auth.accessToken,
                    sessionId = sessionId,
                    beforeOrderSeq = beforeOrderSeq,
                    mode = "before",
                    limit = TIMELINE_PAGE_LIMIT,
                )
                SessionDetailState(
                    session = page.session.toAgentSession(devices.associateBy { it.id }),
                    messages = page.items.flatMap { it.toTimelineMessages() },
                    approvals = page.approvals.map { it.toTimelineApproval() },
                    nextSeq = page.nextSeq,
                    hasMore = page.hasMore,
                    isLoading = false,
                    loadingOlder = false,
                    errorMessage = null,
                )
            }.recoverCatching { error ->
                if (error is ApiException) throw error
                throw IllegalStateException(error.message ?: "Could not load older messages.", error)
            }
        }
    }

    fun streamEvents(sessionId: String, devices: List<AgentDevice>): Flow<SessionStreamEvent> = callbackFlow {
        val auth = runCatching { authSession() }
            .getOrElse {
                trySend(SessionStreamEvent.Failed(it.message ?: "Sign in again to load this session."))
                close(it)
                return@callbackFlow
            }
        val devicesById = devices.associateBy { it.id }
        // Holds the in-flight OkHttp Call so awaitClose can force-close its
        // socket. Cancelling the coroutine alone does NOT unblock the SSE
        // reader (it's parked in a blocking socket read); only Call.cancel()
        // does. Without this, leaving a session leaked the stream's socket, and
        // enough leaks re-created the reconnect storm this fix removes.
        val activeCall = java.util.concurrent.atomic.AtomicReference<okhttp3.Call?>(null)
        val job = launch(Dispatchers.IO) {
            // Exponential backoff for reconnects. A healthy stream stays open for
            // minutes (server sends a 15s keepalive), so reaching onOpen resets the
            // delay to its floor. If the stream fails fast repeatedly, the delay
            // grows toward SSE_RECONNECT_MAX_MS instead of hammering the server
            // (and exhausting client connections) once per second.
            var backoffMs = SSE_RECONNECT_MIN_MS
            while (isActive) {
                try {
                    sessionsApi.streamSessionEvents(
                        serverUrl = auth.serverUrl,
                        authorizationToken = auth.accessToken,
                        sessionId = sessionId,
                        onOpen = {
                            backoffMs = SSE_RECONNECT_MIN_MS
                            trySend(SessionStreamEvent.Connected)
                        },
                        onStart = { call -> activeCall.set(call) },
                    ) { event ->
                        trySend(SessionStreamEvent.Delta(event.toDelta(devicesById)))
                    }
                } catch (error: ApiException) {
                    if (!isActive) break
                    trySend(SessionStreamEvent.Failed(error.message ?: "Session stream failed."))
                    if (error.statusCode == 401 || error.statusCode == 404) break
                } catch (error: Exception) {
                    if (!isActive) break
                    trySend(SessionStreamEvent.Failed(error.message ?: "Session stream failed."))
                } finally {
                    if (isActive) trySend(SessionStreamEvent.Disconnected)
                }
                delay(backoffMs)
                backoffMs = (backoffMs * 2).coerceAtMost(SSE_RECONNECT_MAX_MS)
            }
        }
        awaitClose {
            // Force-close the socket first so a reader parked in readLine()
            // unblocks immediately, then cancel the coroutine.
            activeCall.getAndSet(null)?.cancel()
            job.cancel()
        }
    }

    suspend fun sendMessage(
        sessionId: String,
        content: String,
        clientMessageId: String,
        attachments: List<UploadFilePart> = emptyList(),
        uploadedAttachments: List<TimelineAttachment> = emptyList(),
        maxBudgetUsd: Double? = null,
    ): Result<SendMessageResult> {
        return withContext(Dispatchers.IO) {
            runCatching {
                val auth = authSession()
                val uploaded = if (uploadedAttachments.isNotEmpty()) {
                    uploadedAttachments
                } else if (attachments.isEmpty()) {
                    emptyList()
                } else {
                    sessionsApi.uploadSessionAttachments(
                        serverUrl = auth.serverUrl,
                        authorizationToken = auth.accessToken,
                        sessionId = sessionId,
                        files = attachments,
                    ).map { it.toTimelineAttachment() }
                }
                sessionsApi.sendSessionMessage(
                    serverUrl = auth.serverUrl,
                    authorizationToken = auth.accessToken,
                    sessionId = sessionId,
                    content = content.ifBlank { ATTACHMENT_ONLY_PROMPT },
                    clientMessageId = clientMessageId,
                    attachments = uploaded.map { it.toRemoteUploadedAttachment() },
                    maxBudgetUsd = maxBudgetUsd,
                ).let { response ->
                    SendMessageResult(
                        turnId = response.turnId,
                        attachments = uploaded,
                    )
                }
            }
        }
    }

    suspend fun uploadAttachments(
        sessionId: String,
        attachments: List<UploadFilePart>,
    ): Result<List<TimelineAttachment>> {
        return withContext(Dispatchers.IO) {
            runCatching {
                val auth = authSession()
                sessionsApi.uploadSessionAttachments(
                    serverUrl = auth.serverUrl,
                    authorizationToken = auth.accessToken,
                    sessionId = sessionId,
                    files = attachments,
                ).map { it.toTimelineAttachment() }
            }
        }
    }

    suspend fun setTakeover(
        sessionId: String,
        enabled: Boolean,
        devices: List<AgentDevice>,
    ): Result<AgentSession> {
        return withContext(Dispatchers.IO) {
            runCatching {
                val auth = authSession()
                val session = if (enabled) {
                    sessionsApi.enableTakeover(auth.serverUrl, auth.accessToken, sessionId)
                } else {
                    sessionsApi.disableTakeover(auth.serverUrl, auth.accessToken, sessionId)
                }
                session.toAgentSession(devices.associateBy { it.id })
            }
        }
    }

    suspend fun loadRuntimeSettings(
        sessionId: String,
        runtime: String,
    ): Result<RuntimeSettingsState> {
        return withContext(Dispatchers.IO) {
            runCatching {
                val auth = authSession()
                val schema = sessionsApi.getRuntimeConfigSchema(
                    serverUrl = auth.serverUrl,
                    authorizationToken = auth.accessToken,
                    runtime = runtime,
                )
                val settings = sessionsApi.getSessionRuntimeSettings(
                    serverUrl = auth.serverUrl,
                    authorizationToken = auth.accessToken,
                    sessionId = sessionId,
                )
                settings.toRuntimeSettingsState(schema)
            }
        }
    }

    suspend fun patchRuntimeSettings(
        sessionId: String,
        patch: Map<String, Any?>,
    ): Result<RuntimeSettingsPatchResult> {
        return withContext(Dispatchers.IO) {
            runCatching {
                val auth = authSession()
                val settings = sessionsApi.patchSessionRuntimeSettings(
                    serverUrl = auth.serverUrl,
                    authorizationToken = auth.accessToken,
                    sessionId = sessionId,
                    settings = patch,
                )
                RuntimeSettingsPatchResult(
                    settings = settings.toRuntimeSettingsState(schema = null),
                )
            }
        }
    }

    fun attachmentImageRequest(
        sessionId: String,
        attachment: TimelineAttachment,
    ): Result<AttachmentImageRequest> {
        return runCatching {
            val auth = authSession()
            AttachmentImageRequest(
                url = sessionsApi.attachmentOpenUrl(
                    serverUrl = auth.serverUrl,
                    sessionId = sessionId,
                    fileId = attachment.fileId,
                ),
                authorizationToken = auth.accessToken,
                cacheKey = "attachment:$sessionId:${attachment.fileId}",
            )
        }
    }

    suspend fun interrupt(sessionId: String): Result<Unit> {
        return withContext(Dispatchers.IO) {
            runCatching {
                val auth = authSession()
                sessionsApi.interruptSession(auth.serverUrl, auth.accessToken, sessionId)
                Unit
            }
        }
    }

    suspend fun resolveApproval(
        approvalId: String,
        status: String,
        selections: List<ApprovalSelectionInput> = emptyList(),
    ): Result<Unit> {
        return withContext(Dispatchers.IO) {
            runCatching {
                val auth = authSession()
                sessionsApi.resolveApproval(
                    auth.serverUrl,
                    auth.accessToken,
                    approvalId,
                    status,
                    selections,
                )
                Unit
            }
        }
    }

    fun applyDelta(
        sessionId: String,
        current: SessionDetailState,
        delta: SessionDetailDelta,
    ): SessionDetailState {
        if (delta.refetch) return current
        val keptReal = current.messages.filter { message ->
            !message.optimistic && message.sourceItemId !in delta.replaceSourceItemIds
        }
        val keptOptimistic = current.messages.filter { it.optimistic }
        val messages = mergeOptimistic(
            sessionId = sessionId,
            realMessages = keptReal + delta.messages,
            currentMessages = keptOptimistic,
        )
        return current.copy(
            session = delta.session ?: current.session,
            messages = messages,
            approvals = delta.approvals ?: current.approvals,
            nextSeq = max(current.nextSeq, delta.nextSeq),
            isLoading = false,
            loadingOlder = false,
            errorMessage = null,
        )
    }

    fun applyOlder(
        sessionId: String,
        current: SessionDetailState,
        older: SessionDetailState,
    ): SessionDetailState {
        val realMessages = (older.messages + current.messages.filterNot { it.optimistic })
            .distinctBy { it.id }
        val messages = mergeOptimistic(
            sessionId = sessionId,
            realMessages = realMessages,
            currentMessages = current.messages,
        )
        return current.copy(
            session = older.session ?: current.session,
            messages = messages,
            approvals = older.approvals,
            nextSeq = max(current.nextSeq, older.nextSeq),
            hasMore = older.hasMore,
            loadingOlder = false,
            errorMessage = null,
        )
    }

    fun addOptimisticMessage(
        sessionId: String,
        state: SessionDetailState,
        text: String,
        clientMessageId: String,
        attachments: List<TimelineAttachment> = emptyList(),
    ): SessionDetailState {
        val message = TimelineMessage(
            id = clientMessageId,
            sourceItemId = clientMessageId,
            author = MessageAuthor.User,
            text = text,
            attachments = attachments,
            status = "pending",
            badge = "Sending",
            orderSeq = Int.MAX_VALUE,
            updatedSeq = 0,
            clientMessageId = clientMessageId,
            turnId = null,
            optimistic = true,
        )
        upsertOptimisticMessage(sessionId, message)
        return state.copy(
            messages = mergeOptimistic(
                sessionId = sessionId,
                realMessages = state.messages,
                currentMessages = state.messages + message,
            ),
            sending = true,
            actionError = null,
        )
    }

    fun markOptimisticMessage(
        sessionId: String,
        state: SessionDetailState,
        clientMessageId: String,
        status: String,
        turnId: String? = null,
        attachments: List<TimelineAttachment> = emptyList(),
    ): SessionDetailState {
        val updatedMessages = state.messages.map { message ->
            if (message.id == clientMessageId && message.optimistic) {
                message.copy(
                    status = status,
                    badge = status.statusLabel(),
                    turnId = turnId ?: message.turnId,
                    attachments = attachments.ifEmpty { message.attachments },
                )
            } else {
                message
            }
        }
        replaceOptimisticMessages(
            sessionId = sessionId,
            messages = updatedMessages.filter { it.optimistic },
        )
        return state.copy(
            messages = mergeOptimistic(
                sessionId = sessionId,
                realMessages = state.messages,
                currentMessages = updatedMessages,
            ),
            sending = false,
            actionError = if (status == "failed") state.actionError else null,
        )
    }

    private fun authSession(): ApiAuth {
        val serverUrl = sessionStore.readServerUrl()
        val accessToken = sessionStore.readAccessToken()
        if (serverUrl.isBlank() || accessToken.isBlank()) {
            throw IllegalStateException("Sign in again to load this session.")
        }
        return ApiAuth(serverUrl = serverUrl, accessToken = accessToken)
    }

    private fun RemoteSessionEvent.toDelta(devicesById: Map<String, AgentDevice>): SessionDetailDelta {
        val sourceIds = items.map { it.id }.toSet()
        return SessionDetailDelta(
            session = session?.toAgentSession(devicesById),
            messages = items.flatMap { it.toTimelineMessages() },
            replaceSourceItemIds = sourceIds,
            approvals = approvals?.map { it.toTimelineApproval() },
            nextSeq = nextSeq,
            refetch = refetch,
        )
    }

    private fun RemoteRuntimeSettings.toRuntimeSettingsState(
        schema: RemoteRuntimeConfigSchema?,
    ): RuntimeSettingsState {
        return RuntimeSettingsState(
            schema = schema?.toRuntimeConfigSchema(),
            settings = settings,
            overrideSettings = runtimeSettingsOverride,
            isLoading = false,
            savingKey = null,
            errorMessage = null,
        )
    }

    private fun RemoteRuntimeConfigSchema.toRuntimeConfigSchema(): RuntimeConfigSchema {
        return RuntimeConfigSchema(
            runtime = runtime,
            schemaVersion = schemaVersion,
            fields = fields.map { it.toRuntimeConfigField() },
        )
    }

    private fun RemoteRuntimeConfigField.toRuntimeConfigField(): RuntimeConfigField {
        return RuntimeConfigField(
            key = key,
            label = label,
            type = type,
            description = description,
            options = options.map { it.toRuntimeConfigOption() },
            visibleWhen = visibleWhen,
            allowSessionOverride = allowSessionOverride,
            hidden = hidden,
        )
    }

    private fun RemoteRuntimeConfigOption.toRuntimeConfigOption(): RuntimeConfigOption {
        return RuntimeConfigOption(
            value = value,
            label = label,
            description = description,
            efforts = efforts?.map { it.toRuntimeConfigOption() },
        )
    }

    private fun RemoteApproval.toTimelineApproval(): TimelineApproval {
        return TimelineApproval(
            id = id,
            title = title,
            description = description,
            kind = kind,
            status = status,
            choices = choices,
            questions = questions.map { question ->
                ApprovalQuestion(
                    header = question.header,
                    question = question.question,
                    multiSelect = question.multiSelect,
                    options = question.options.map { option ->
                        ApprovalQuestionOption(
                            label = option.label,
                            description = option.description,
                        )
                    },
                )
            },
            updatedSeq = updatedSeq,
        )
    }

    private fun mergeOptimistic(
        sessionId: String,
        realMessages: List<TimelineMessage>,
        currentMessages: List<TimelineMessage>,
    ): List<TimelineMessage> {
        val real = realMessages.filterNot { it.optimistic }
        val optimistic = (currentMessages.filter { it.optimistic } + optimisticMessages(sessionId))
            .distinctBy { it.id }
        val pending = optimistic.filter { optimisticMessage ->
            optimisticMessage.status == "failed" ||
                real.none { realMessage -> realMessage.matchesClientMessage(optimisticMessage.id) }
        }
        replaceOptimisticMessages(sessionId, pending)
        return sortMessages(real + pending)
    }

    private fun optimisticMessages(sessionId: String): List<TimelineMessage> {
        return synchronized(optimisticLock) {
            optimisticMessagesBySession[sessionId].orEmpty()
        }
    }

    private fun upsertOptimisticMessage(sessionId: String, message: TimelineMessage) {
        synchronized(optimisticLock) {
            val messages = optimisticMessagesBySession[sessionId].orEmpty()
                .filterNot { it.id == message.id } + message
            optimisticMessagesBySession[sessionId] = sortMessages(messages)
        }
    }

    private fun replaceOptimisticMessages(sessionId: String, messages: List<TimelineMessage>) {
        synchronized(optimisticLock) {
            if (messages.isEmpty()) {
                optimisticMessagesBySession.remove(sessionId)
            } else {
                optimisticMessagesBySession[sessionId] = sortMessages(messages.filter { it.optimistic })
            }
        }
    }

    private fun sortMessages(messages: List<TimelineMessage>): List<TimelineMessage> {
        return messages.sortedWith(
            compareBy<TimelineMessage> { it.orderSeq }
                .thenBy { it.updatedSeq }
                .thenBy { it.id },
        )
    }

    private fun TimelineMessage.matchesClientMessage(clientMessageId: String): Boolean {
        return author == MessageAuthor.User && this.clientMessageId == clientMessageId
    }

    private fun List<TimelineMessage>.hasPendingOptimisticSend(): Boolean {
        return any { it.optimistic && it.status == "pending" }
    }

    private fun RemoteUploadedAttachment.toTimelineAttachment(): TimelineAttachment {
        return TimelineAttachment(
            fileId = fileId,
            name = name,
            mediaType = mediaType,
            size = size,
        )
    }

    private fun TimelineAttachment.toRemoteUploadedAttachment(): RemoteUploadedAttachment {
        return RemoteUploadedAttachment(
            fileId = fileId,
            name = name,
            mediaType = mediaType,
            size = size,
        )
    }

    private fun JSONObject.toTimelineAttachmentOrNull(): TimelineAttachment? {
        val fileId = text("fileId")?.takeIf { it.isNotBlank() } ?: return null
        return TimelineAttachment(
            fileId = fileId,
            name = text("name") ?: fileId,
            mediaType = text("mediaType").orEmpty(),
            size = optLong("size", 0L),
        )
    }

    private fun RemoteTimelineItem.toTimelineMessages(): List<TimelineMessage> {
        return when (type) {
            "message" -> listOf(toTextMessage())
            "tool" -> toToolMessages()
            "system" -> listOfNotNull(toSystemMessage())
            "artifact" -> if (content.text("kind") == "diff") emptyList() else listOfNotNull(toSystemMessage())
            "turn.start", "turn.end" -> null
            else -> listOfNotNull(toSystemMessage())
        } ?: emptyList()
    }

    private fun RemoteTimelineItem.toToolMessages(): List<TimelineMessage> {
        return when (content.text("kind")) {
            "command" -> listOf(toCommandMessage())
            "file_change" -> toFileChangeMessages()
            "web_search" -> listOf(toToolCallMessage(title = "Searched web", subtitle = content.text("query").orEmpty()))
            "mcp" -> {
                val argsJson = content.optJSONObject("arguments")?.toString(2) ?: ""
                val outputText = content.text("outputText") ?: content.text("result") ?: ""
                val errorText = content.text("error") ?: ""
                val isError = content.optBoolean("isError", false) || errorText.isNotBlank()
                val body = when {
                    isError && errorText.isNotBlank() -> "Error: $errorText"
                    outputText.isNotBlank() -> outputText
                    else -> ""
                }
                listOf(
                    toToolCallMessage(
                        title = content.text("tool") ?: "tool",
                        subtitle = content.text("server") ?: "mcp",
                        detail = argsJson,
                        body = body,
                    )
                )
            }
            "schedule_wakeup" -> {
                val delay = content.text("delaySeconds")?.let { formatDelaySeconds(it) }
                val title = if (delay != null) "Scheduled wake-up in $delay" else "Scheduled wake-up"
                listOf(toToolCallMessage(title = title, subtitle = content.text("reason").orEmpty()))
            }
            "task_stop" -> {
                val target = content.text("target")
                val title = if (target != null) "Stopped sub-agent $target" else "Stopped sub-agent"
                listOf(toToolCallMessage(title = title, subtitle = target.orEmpty()))
            }
            "tool_search" -> {
                val query = content.text("query")
                val title = if (query != null) "Searched tools for $query" else "Searched tools"
                listOf(toToolCallMessage(title = title, subtitle = query.orEmpty()))
            }
            else -> listOf(toToolCallMessage(title = shortToolTitle(), subtitle = content.text("kind").orEmpty()))
        }
    }

    private fun RemoteTimelineItem.toTextMessage(): TimelineMessage {
        val author = when (role) {
            "user" -> MessageAuthor.User
            "assistant" -> MessageAuthor.Agent
            else -> MessageAuthor.Tool
        }
        return TimelineMessage(
            id = id,
            sourceItemId = id,
            author = author,
            text = (text.ifBlank { content.text("text").orEmpty() }).stripInjectedAttachmentMentions(),
            attachments = content.records("attachments").mapNotNull { it.toTimelineAttachmentOrNull() },
            status = status,
            type = type,
            badge = status.statusLabel(),
            orderSeq = orderSeq,
            updatedSeq = updatedSeq,
            clientMessageId = source.text("clientMessageId"),
            turnId = turnId,
            parentItemId = parentItemId,
        )
    }

    private fun RemoteTimelineItem.toSystemMessage(): TimelineMessage? {
        val kind = content.text("kind") ?: "system"
        if (kind == "reasoning") {
            val summaries = content.records("summaries").mapNotNull { it.text("text") }
            val rawText = content.text("rawText") ?: content.text("text")
            val body = (if (summaries.isNotEmpty()) summaries else listOfNotNull(rawText))
                .joinToString("\n\n")
            return TimelineMessage(
                id = id,
                sourceItemId = id,
                author = MessageAuthor.Agent,
                text = body,
                status = status,
                type = type,
                kind = TimelineMessageKind.Reasoning,
                title = "Reasoning",
                badge = status.statusLabel(),
                orderSeq = orderSeq,
                updatedSeq = updatedSeq,
                clientMessageId = source.text("clientMessageId"),
                turnId = turnId,
                parentItemId = parentItemId,
                createdAt = createdAt,
                completedAt = completedAt,
                redacted = content.text("redacted") == "true",
            )
        }
        if (kind == "compact") {
            // Context-compaction separator. Carry the before/after token counts
            // in the subtitle ("160,000 -> 42,000 tokens") when the connector
            // supplied them; the card renders a non-expandable divider.
            val pre = if (content.has("preTokens")) content.optLong("preTokens", -1L) else -1L
            val post = if (content.has("postTokens")) content.optLong("postTokens", -1L) else -1L
            val subtitle = if (pre >= 0 && post >= 0) {
                "${"%,d".format(pre)} → ${"%,d".format(post)}"
            } else {
                ""
            }
            return TimelineMessage(
                id = id,
                sourceItemId = id,
                author = MessageAuthor.Tool,
                text = "",
                status = status,
                type = type,
                kind = TimelineMessageKind.Compact,
                subtitle = subtitle,
                orderSeq = orderSeq,
                updatedSeq = updatedSeq,
                turnId = turnId,
                parentItemId = parentItemId,
            )
        }
        if (kind == "notification") {
            // CLI-initiated Notification hook: a message asking for the user's
            // attention. The title is optional; fall back to a generic label in
            // the card when absent.
            val message = content.text("message") ?: content.text("text")
            if (message.isNullOrBlank()) return null
            return TimelineMessage(
                id = id,
                sourceItemId = id,
                author = MessageAuthor.Tool,
                text = message,
                status = status,
                type = type,
                kind = TimelineMessageKind.Notification,
                title = content.text("title").orEmpty(),
                orderSeq = orderSeq,
                updatedSeq = updatedSeq,
                clientMessageId = source.text("clientMessageId"),
                turnId = turnId,
                parentItemId = parentItemId,
            )
        }
        if (kind == "skill_listing") {
            val skills = content.records("skills").map { s ->
                SkillItem(
                    name = s.text("name").orEmpty(),
                    description = s.text("description").orEmpty(),
                )
            }.filter { it.name.isNotBlank() }
            if (skills.isEmpty()) return null
            return TimelineMessage(
                id = id, sourceItemId = id,
                author = MessageAuthor.Tool,
                text = "",
                status = status, type = type,
                kind = TimelineMessageKind.SkillListing,
                skills = skills,
                orderSeq = orderSeq, updatedSeq = updatedSeq,
                turnId = turnId, parentItemId = parentItemId,
            )
        }
        if (kind == "deferred_tools_delta") {
            val added = content.optJSONArray("addedNames").toStringList()
            val removed = content.optJSONArray("removedNames").toStringList()
            if (added.isEmpty() && removed.isEmpty()) return null
            return TimelineMessage(
                id = id, sourceItemId = id,
                author = MessageAuthor.Tool,
                text = "",
                status = status, type = type,
                kind = TimelineMessageKind.DeferredToolsDelta,
                addedToolNames = added,
                removedToolNames = removed,
                orderSeq = orderSeq, updatedSeq = updatedSeq,
                turnId = turnId, parentItemId = parentItemId,
            )
        }
        if (kind == "invoked_skills") {
            val skills = content.records("skills").map { s ->
                SkillItem(
                    name = s.text("name").orEmpty(),
                    path = s.text("path").orEmpty(),
                )
            }.filter { it.name.isNotBlank() }
            if (skills.isEmpty()) return null
            return TimelineMessage(
                id = id, sourceItemId = id,
                author = MessageAuthor.Tool,
                text = "",
                status = status, type = type,
                kind = TimelineMessageKind.InvokedSkills,
                skills = skills,
                orderSeq = orderSeq, updatedSeq = updatedSeq,
                turnId = turnId, parentItemId = parentItemId,
            )
        }
        val message = content.text("message") ?: content.text("text") ?: kind
        if (message.isBlank()) return null
        return TimelineMessage(
            id = id,
            sourceItemId = id,
            author = MessageAuthor.Tool,
            text = message,
            status = status,
            type = type,
            kind = TimelineMessageKind.System,
            title = kind,
            badge = status.statusLabel(),
            orderSeq = orderSeq,
            updatedSeq = updatedSeq,
            clientMessageId = source.text("clientMessageId"),
            turnId = turnId,
            parentItemId = parentItemId,
        )
    }

    private fun RemoteTimelineItem.toCommandMessage(): TimelineMessage {
        val command = content.opt("command").commandText()
        val description = content.text("description") ?: command
        val output = content.text("outputPreview") ?: content.text("outputText").orEmpty()
        val exit = content.text("exitCode")?.let { "exit code $it" }.orEmpty()
        return TimelineMessage(
            id = id,
            sourceItemId = id,
            author = MessageAuthor.Tool,
            text = description.ifBlank { "command" },
            status = status,
            type = type,
            kind = TimelineMessageKind.Command,
            title = "Ran",
            subtitle = description.ifBlank { command.ifBlank { "command" } },
            badge = status.statusLabel(),
            detail = command,
            body = listOf(output, exit).filter { it.isNotBlank() }.joinToString("\n"),
            orderSeq = orderSeq,
            updatedSeq = updatedSeq,
            clientMessageId = source.text("clientMessageId"),
            turnId = turnId,
            parentItemId = parentItemId,
        )
    }

    private fun RemoteTimelineItem.toFileChangeMessages(): List<TimelineMessage> {
        val changes = content.records("changes")
        if (changes.isEmpty()) return listOf(toFileChangeMessage(JSONObject(), 0))
        return changes.mapIndexed { index, change -> toFileChangeMessage(change, index) }
    }

    private fun RemoteTimelineItem.toFileChangeMessage(change: JSONObject, index: Int): TimelineMessage {
        val targetPath = change.text("path").orEmpty()
        val filename = targetPath.substringAfterLast('/').ifBlank { targetPath.ifBlank { "files" } }
        val verb = change.fileChangeVerb()
        return TimelineMessage(
            id = if (index == 0) id else "$id:$index",
            sourceItemId = id,
            author = MessageAuthor.Tool,
            text = "$verb $filename",
            status = status,
            type = type,
            kind = TimelineMessageKind.FileChange,
            title = verb,
            subtitle = filename,
            badge = status.statusLabel(),
            detail = targetPath,
            body = change.text("diff").orEmpty(),
            orderSeq = orderSeq,
            updatedSeq = updatedSeq,
            clientMessageId = source.text("clientMessageId"),
            turnId = turnId,
            parentItemId = parentItemId,
        )
    }

    private fun RemoteTimelineItem.toToolCallMessage(
        title: String,
        subtitle: String,
        detail: String = "",
        body: String = "",
    ): TimelineMessage {
        val name = title.ifBlank { "tool" }
        return TimelineMessage(
            id = id,
            sourceItemId = id,
            author = MessageAuthor.Tool,
            text = name,
            // A tool_result can carry inline images the connector externalized to
            // fileId refs (e.g. a Read of a screenshot). Surface them the same way
            // user-message attachments are rendered so the tool card shows the image.
            attachments = content.records("attachments").mapNotNull { it.toTimelineAttachmentOrNull() },
            status = status,
            type = type,
            kind = TimelineMessageKind.ToolCall,
            title = name,
            subtitle = subtitle,
            detail = detail,
            body = body,
            badge = status.statusLabel(),
            orderSeq = orderSeq,
            updatedSeq = updatedSeq,
            clientMessageId = source.text("clientMessageId"),
            turnId = turnId,
            parentItemId = parentItemId,
            subagent = content.subagentProgress(),
        )
    }

    private fun formatDelaySeconds(raw: String): String? {
        val total = raw.toDoubleOrNull()?.toInt() ?: return null
        val seconds = total.coerceAtLeast(0)
        if (seconds < 60) return "${seconds}s"
        val minutes = Math.round(seconds / 60.0).toInt()
        if (minutes < 60) return "${minutes}m"
        val hours = minutes / 60
        val rem = minutes % 60
        return if (rem == 0) "${hours}h" else "${hours}h ${rem}m"
    }

    private fun RemoteTimelineItem.shortToolTitle(): String {
        return content.text("function")
            ?: content.text("name")
            ?: content.text("tool")
            ?: content.text("kind")
            ?: "tool"
    }

    private fun RemoteSession.toAgentSession(devicesById: Map<String, AgentDevice>): AgentSession {
        val statusValue = status.toSessionStatus()
        val runtimeText = runtime.runtimeLabel()
        val deviceName = devicesById[connectorId]?.name ?: connectorId.take(8).ifBlank { "Device" }
        val workspace = cwd?.trim()?.trimEnd('/')?.substringAfterLast('/').orEmpty()
        return AgentSession(
            id = id,
            connectorId = connectorId,
            deviceName = deviceName,
            title = title?.takeIf { it.isNotBlank() }
                ?: externalSessionId?.takeIf { it.isNotBlank() }
                ?: "Untitled session",
            summary = cwd.orEmpty(),
            cwd = cwd,
            workspaceLabel = workspace,
            runtime = runtime,
            runtimeLabel = runtimeText,
            status = statusValue,
            statusLabel = statusValue.statusLabel(),
            updatedAtLabel = "",
            metaLabel = listOf(runtimeText, deviceName, workspace)
                .filter { it.isNotBlank() }
                .joinToString("  ·  "),
            pinned = pinned,
            archived = archived,
            unread = unread,
            takeover = takeover,
            connectorOnline = connectorStatus == "online",
            runtimeSettings = runtimeSettings,
            runtimeSettingsOverride = runtimeSettingsOverride,
            live = statusValue == SessionStatus.Running || statusValue == SessionStatus.WaitingApproval,
            sortKey = sortAt ?: lastActivityAt ?: lastItemAt ?: "",
            contextUsage = contextUsage?.toContextUsage(),
            rateLimit = rateLimit?.toRateLimit(),
            sessionMeta = sessionMeta?.toSessionMeta(),
        )
    }

    private fun String.toSessionStatus(): SessionStatus {
        return when (this) {
            "running" -> SessionStatus.Running
            "waiting_approval" -> SessionStatus.WaitingApproval
            "error" -> SessionStatus.Error
            else -> SessionStatus.Idle
        }
    }

    private fun SessionStatus.statusLabel(): String {
        return when (this) {
            SessionStatus.Idle -> "Idle"
            SessionStatus.Running -> "Running"
            SessionStatus.WaitingApproval -> "Approval"
            SessionStatus.Error -> "Error"
        }
    }

    private fun String.statusLabel(): String {
        return when (this) {
            "pending" -> "Pending"
            "running" -> "Running"
            "waiting_approval" -> "Approval"
            "done" -> "Done"
            "failed" -> "Failed"
            "cancelled" -> "Cancelled"
            "interrupted" -> "Stopped"
            else -> replace('_', ' ').replaceFirstChar { it.uppercase() }
        }
    }

    private fun JSONObject.text(name: String): String? {
        if (!has(name) || isNull(name)) return null
        return when (val value = opt(name)) {
            is String -> value.takeIf { it.isNotBlank() }
            is Number, is Boolean -> value.toString()
            else -> null
        }
    }

    private fun JSONObject.records(name: String): List<JSONObject> {
        val array = optJSONArray(name) ?: return emptyList()
        return List(array.length()) { index -> array.optJSONObject(index) }.filterNotNull()
    }

    // Sub-agent (Agent tool) progress rides on the parent tool card's
    // content.subagent (see connector _emit_task_progress); a real-time-only
    // signal, absent on ordinary tool cards.
    private fun JSONObject.subagentProgress(): SubagentProgress? {
        val subagent = optJSONObject("subagent") ?: return null
        val usage = subagent.optJSONObject("usage")
        return SubagentProgress(
            status = subagent.text("status").orEmpty(),
            finished = subagent.optBoolean("finished", false),
            totalTokens = usage?.optLong("totalTokens", 0L) ?: 0L,
            toolUses = usage?.optLong("toolUses", 0L) ?: 0L,
            durationMs = usage?.optLong("durationMs", 0L) ?: 0L,
        )
    }

    private fun JSONObject.fileChangeVerb(): String {
        val kind = optJSONObject("kind")
        val type = kind?.text("type") ?: text("action")
        return when (type) {
            "add" -> "Added"
            "delete" -> "Deleted"
            "update" -> if (kind?.text("move_path") != null) "Renamed" else "Edited"
            else -> "Changed"
        }
    }

    private fun Any?.commandText(): String {
        return when (this) {
            is String -> this
            is JSONArray -> List(length()) { index -> opt(index).toString() }.joinToString(" ")
            else -> ""
        }
    }

    private fun String.stripInjectedAttachmentMentions(): String {
        val markers = listOf(
            "\n\n[Attached file: ",
            "\n\n[Failed to load attachment ",
            "\n\n[Attachments dropped ",
        )
        val cut = markers
            .map { marker -> indexOf(marker) }
            .filter { it >= 0 }
            .minOrNull() ?: length
        return take(cut).trimEnd()
    }

    private data class ApiAuth(
        val serverUrl: String,
        val accessToken: String,
    )

    private companion object {
        const val ATTACHMENT_ONLY_PROMPT = "(No text content.)"
    }
}

data class SendMessageResult(
    val turnId: String?,
    val attachments: List<TimelineAttachment>,
)

data class RuntimeSettingsPatchResult(
    val settings: RuntimeSettingsState,
)
