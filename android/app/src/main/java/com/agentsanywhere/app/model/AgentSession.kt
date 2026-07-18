package com.agentsanywhere.app.model

data class AgentSession(
    val id: String,
    val connectorId: String,
    val deviceName: String,
    val title: String,
    val summary: String,
    val cwd: String?,
    val workspaceLabel: String,
    val runtime: String,
    val runtimeLabel: String,
    val status: SessionStatus,
    val statusLabel: String,
    val updatedAtLabel: String,
    val metaLabel: String,
    val pinned: Boolean,
    val archived: Boolean,
    val unread: Boolean,
    val takeover: Boolean,
    val connectorOnline: Boolean,
    val runtimeSettings: Map<String, Any?> = emptyMap(),
    val runtimeSettingsOverride: Map<String, Any?> = emptyMap(),
    val live: Boolean,
    val sortKey: String,
    // Context-window occupancy gauge (from the connector's get_context_usage()).
    // Null until the first turn reports it, or when the runtime doesn't emit it.
    val contextUsage: ContextUsage? = null,
    // Rate-limit snapshot (from the connector's RateLimitEvent). Null until the
    // first event; status "allowed" means no warning, "allowed_warning"/
    // "rejected" surface a quota banner with the reset time.
    val rateLimit: RateLimit? = null,
    val externalSessionId: String? = null,
    val tag: String? = null,
)

// Compact context-window gauge shown in the session header: how full the
// context is and whether autocompact is about to fire.
data class ContextUsage(
    val totalTokens: Long? = null,
    val maxTokens: Long? = null,
    val percentage: Double? = null,
    val autoCompactEnabled: Boolean = false,
    val autoCompactThreshold: Long? = null,
)

// Rate-limit state shown in the session header. status "allowed" hides the
// badge; "allowed_warning"/"rejected" show a quota warning with the reset time.
data class RateLimit(
    val status: String? = null,
    val type: String? = null,
    val resetsAt: Long? = null,
    val utilization: Double? = null,
    val overageStatus: String? = null,
    val overageResetsAt: Long? = null,
)

enum class SessionStatus {
    Idle,
    Running,
    WaitingApproval,
    Error,
}

data class AgentDevice(
    val id: String,
    val name: String,
    val deviceOs: String? = null,
    val subtitle: String,
    val online: Boolean,
    val attachedRuntimes: List<String> = emptyList(),
    val lastSeenAt: String? = null,
    val createdAt: String? = null,
)

data class RemoteFile(
    val name: String,
    val path: String,
    val type: RemoteFileType,
)

enum class RemoteFileType {
    File,
    Directory,
}
