package com.agentsanywhere.app.feature.sessiondetail

import com.agentsanywhere.app.model.AgentSession

data class SessionDetailState(
    val session: AgentSession? = null,
    val messages: List<TimelineMessage> = emptyList(),
    val approvals: List<TimelineApproval> = emptyList(),
    val nextSeq: Int = 0,
    val hasMore: Boolean = false,
    val isLoading: Boolean = false,
    val loadingOlder: Boolean = false,
    val errorMessage: String? = null,
    val actionError: String? = null,
    // Starts true so the "reconnecting" banner never flashes during the initial
    // connect; flips to false only when the stream actually disconnects/fails.
    val sseConnected: Boolean = true,
    val takeoverInFlight: Boolean = false,
    val sending: Boolean = false,
    val interrupting: Boolean = false,
    val runtimeSettings: RuntimeSettingsState = RuntimeSettingsState(),
)

data class RuntimeSettingsState(
    val schema: RuntimeConfigSchema? = null,
    val settings: Map<String, Any?> = emptyMap(),
    val overrideSettings: Map<String, Any?> = emptyMap(),
    val isLoading: Boolean = false,
    val savingKey: String? = null,
    val errorMessage: String? = null,
)

data class RuntimeConfigSchema(
    val runtime: String,
    val schemaVersion: Int,
    val fields: List<RuntimeConfigField>,
)

data class RuntimeConfigField(
    val key: String,
    val label: String,
    val type: String,
    val description: String?,
    val options: List<RuntimeConfigOption>,
    val visibleWhen: Map<String, Any?>,
    val allowSessionOverride: Boolean,
    val hidden: Boolean,
)

data class RuntimeConfigOption(
    val value: String,
    val label: String,
    val description: String?,
    val efforts: List<RuntimeConfigOption>? = null,
)

data class TimelineMessage(
    val id: String,
    val sourceItemId: String = id,
    val author: MessageAuthor,
    val text: String,
    val attachments: List<TimelineAttachment> = emptyList(),
    val status: String = "done",
    val type: String = "message",
    val kind: TimelineMessageKind = TimelineMessageKind.Text,
    val title: String = "",
    val subtitle: String = "",
    val badge: String = "",
    val detail: String = "",
    val body: String = "",
    val orderSeq: Int = 0,
    val updatedSeq: Int = 0,
    val clientMessageId: String? = null,
    val turnId: String? = null,
    // Timeline id of the parent Task (sub-agent) card, when this item was
    // produced inside a sub-agent. Null for top-level conversation items.
    val parentItemId: String? = null,
    val optimistic: Boolean = false,
    // ISO timestamp the item converged to a terminal state. Paired with the
    // item's creation time it yields a reasoning block's thinking duration.
    val createdAt: String = "",
    val completedAt: String? = null,
    // True for a redacted (encrypted) reasoning block whose prose is withheld;
    // the card still renders so the user knows the model reasoned.
    val redacted: Boolean = false,
    // Sub-agent (Agent tool) progress folded onto the parent tool card as
    // content.subagent. Real-time-only; null for ordinary tool cards.
    val subagent: SubagentProgress? = null,
    // Attachment-derived fields for SkillListing / InvokedSkills items.
    val skills: List<SkillItem> = emptyList(),
    // Attachment-derived fields for DeferredToolsDelta items.
    val addedToolNames: List<String> = emptyList(),
    val removedToolNames: List<String> = emptyList(),
)

// Live progress of a spawned sub-agent, surfaced on its parent Agent tool card.
// finished is true once the sub-agent reaches a terminal status.
data class SubagentProgress(
    val status: String = "",
    val finished: Boolean = false,
    val totalTokens: Long = 0,
    val toolUses: Long = 0,
    val durationMs: Long = 0,
)

data class TimelineAttachment(
    val fileId: String,
    val name: String,
    val mediaType: String,
    val size: Long,
) {
    val isImage: Boolean
        get() = mediaType.startsWith("image/")
}

data class AttachmentImageRequest(
    val url: String,
    val authorizationToken: String,
    val cacheKey: String,
)

data class TimelineApproval(
    val id: String,
    val title: String,
    val description: String?,
    val kind: String,
    val status: String,
    val choices: List<String>,
    // AskUserQuestion questions; empty for plain permission approvals.
    val questions: List<ApprovalQuestion>,
    val updatedSeq: Int,
)

data class ApprovalQuestion(
    val header: String?,
    val question: String,
    val multiSelect: Boolean,
    val options: List<ApprovalQuestionOption>,
)

data class ApprovalQuestionOption(
    val label: String,
    val description: String?,
)

sealed interface SessionStreamEvent {
    data object Connected : SessionStreamEvent
    data object Disconnected : SessionStreamEvent
    data class Delta(val value: SessionDetailDelta) : SessionStreamEvent
    data class Failed(val message: String) : SessionStreamEvent
}

data class SessionDetailDelta(
    val session: AgentSession? = null,
    val messages: List<TimelineMessage> = emptyList(),
    val replaceSourceItemIds: Set<String> = emptySet(),
    val approvals: List<TimelineApproval>? = null,
    val nextSeq: Int = 0,
    val refetch: Boolean = false,
)

enum class MessageAuthor {
    User,
    Agent,
    Tool,
}

enum class TimelineMessageKind {
    Text,
    Reasoning,
    Command,
    FileChange,
    ToolCall,
    System,
    // Context-compaction boundary: a non-expandable separator ("context
    // compacted: N -> M tokens") the connector emits where the CLI auto-
    // compacted the window, so the user knows why earlier history vanished.
    Compact,
    // CLI-initiated Notification hook: a message asking for the user's
    // attention (e.g. a permission prompt) surfaced as its own card.
    Notification,
    // Attachment subtypes from JSONL transcript, surfaced as system items.
    SkillListing,
    DeferredToolsDelta,
    InvokedSkills,
}

data class SkillItem(val name: String, val description: String = "", val path: String = "")
