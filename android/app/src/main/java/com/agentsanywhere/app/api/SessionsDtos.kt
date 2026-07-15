package com.agentsanywhere.app.api

import com.agentsanywhere.app.model.ContextUsage
import com.agentsanywhere.app.model.RateLimit
import org.json.JSONObject


data class RemoteSession(
    val id: String,
    val connectorId: String,
    val connectorStatus: String,
    val runtime: String,
    val externalSessionId: String?,
    val title: String?,
    val cwd: String?,
    val status: String,
    val takeover: Boolean,
    val pinned: Boolean,
    val archived: Boolean,
    val unread: Boolean,
    val lastSyncedAt: String?,
    val sourceObservedAt: String?,
    val lastActivityAt: String?,
    val lastItemAt: String?,
    val sortAt: String?,
    val updatedSeq: Int,
    val runtimeSettings: Map<String, Any?>,
    val runtimeSettingsOverride: Map<String, Any?>,
    val contextUsage: RemoteContextUsage? = null,
    val rateLimit: RemoteRateLimit? = null,
)

data class RemoteContextUsage(
    val totalTokens: Long? = null,
    val maxTokens: Long? = null,
    val percentage: Double? = null,
    val autoCompactEnabled: Boolean = false,
    val autoCompactThreshold: Long? = null,
)

data class RemoteRateLimit(
    val status: String? = null,
    val type: String? = null,
    val resetsAt: Long? = null,
    val utilization: Double? = null,
    val overageStatus: String? = null,
    val overageResetsAt: Long? = null,
)

data class RemoteRuntimeConfigSchema(
    val runtime: String,
    val schemaVersion: Int,
    val fields: List<RemoteRuntimeConfigField>,
)

data class RemoteRuntimeConfigField(
    val key: String,
    val label: String,
    val type: String,
    val description: String?,
    val options: List<RemoteRuntimeConfigOption>,
    val visibleWhen: Map<String, Any?>,
    val allowSessionOverride: Boolean,
    val hidden: Boolean,
)

data class RemoteRuntimeConfigOption(
    val value: String,
    val label: String,
    val description: String?,
    val efforts: List<RemoteRuntimeConfigOption>?,
)

data class RemoteRuntimeSettings(
    val runtime: String,
    val settings: Map<String, Any?>,
    val runtimeSettingsOverride: Map<String, Any?>,
    val schemaVersion: Int,
)

data class RemoteSessionState(
    val session: RemoteSession,
    val items: List<RemoteTimelineItem>,
    val approvals: List<RemoteApproval>,
    val nextSeq: Int,
    val hasMore: Boolean,
)

data class RemoteTimelineItem(
    val id: String,
    val sessionId: String,
    val turnId: String?,
    val type: String,
    val status: String,
    val role: String?,
    val text: String,
    val content: JSONObject,
    val source: JSONObject,
    val orderSeq: Int,
    val updatedSeq: Int,
    val createdAt: String,
    // Set when the item converges to a terminal state; used to derive how long a
    // reasoning block took (completedAt - createdAt). Null while still running.
    val completedAt: String? = null,
    // Set when this item is sub-agent (Task tool) output; holds the timeline id
    // of the parent Task card so the UI can nest it under that card.
    val parentItemId: String? = null,
)

data class RemoteApproval(
    val id: String,
    val sessionId: String,
    val turnId: String?,
    val status: String,
    val kind: String,
    val targetItemId: String?,
    val title: String,
    val description: String?,
    val choices: List<String>,
    // AskUserQuestion questions parsed from payload.input.questions; empty for
    // plain permission approvals.
    val questions: List<RemoteApprovalQuestion>,
    val updatedSeq: Int,
    val createdAt: String,
)

data class RemoteApprovalQuestion(
    val header: String?,
    val question: String,
    val multiSelect: Boolean,
    val options: List<RemoteApprovalQuestionOption>,
)

data class RemoteApprovalQuestionOption(
    val label: String,
    val description: String?,
)

// One resolved answer sent back on resolve: question text plus chosen label(s).
// A free-text "Other" answer is just a label string.
data class ApprovalSelectionInput(
    val question: String,
    val labels: List<String>,
)

data class RemoteSessionEvent(
    val sessionId: String,
    val items: List<RemoteTimelineItem>,
    val approvals: List<RemoteApproval>?,
    val session: RemoteSession?,
    val nextSeq: Int,
    val refetch: Boolean,
)

data class RemoteRpcResponse(
    val ok: Boolean,
    val turnId: String?,
)

data class RemoteUploadedAttachment(
    val fileId: String,
    val name: String,
    val mediaType: String,
    val size: Long,
)

internal fun RemoteContextUsage.toContextUsage(): ContextUsage {
    return ContextUsage(
        totalTokens = totalTokens,
        maxTokens = maxTokens,
        percentage = percentage,
        autoCompactEnabled = autoCompactEnabled,
        autoCompactThreshold = autoCompactThreshold,
    )
}

internal fun RemoteRateLimit.toRateLimit(): RateLimit {
    return RateLimit(
        status = status,
        type = type,
        resetsAt = resetsAt,
        utilization = utilization,
        overageStatus = overageStatus,
        overageResetsAt = overageResetsAt,
    )
}
