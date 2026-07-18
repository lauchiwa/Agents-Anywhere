package com.agentsanywhere.app.api

import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

enum class McpServerType { stdio, http, sse }

data class McpServerConfig(
    val type: McpServerType,
    val command: String? = null,
    val args: List<String>? = null,
    val env: Map<String, String>? = null,
    val url: String? = null,
    val headers: Map<String, String>? = null,
)

data class McpServerDraft(
    val id: String = UUID.randomUUID().toString(),
    val name: String = "",
    val type: McpServerType = McpServerType.stdio,
    val command: String = "",
    val argsText: String = "",
    val env: List<Pair<String, String>> = emptyList(),
    val url: String = "",
    val headers: List<Pair<String, String>> = emptyList(),
)

// --- JSON helpers ---

fun JSONObject.toStringMap(): Map<String, String> =
    keys().asSequence().associateWith { getString(it) }

fun Map<String, String>.toStringJsonObject(): JSONObject =
    JSONObject().also { obj -> forEach { (k, v) -> obj.put(k, v) } }

fun JSONObject.toMcpServerConfig(): McpServerConfig {
    val type = McpServerType.valueOf(getString("type"))
    return when (type) {
        McpServerType.stdio -> McpServerConfig(
            type = type,
            command = optString("command").ifEmpty { null },
            args = optJSONArray("args")?.let { arr -> (0 until arr.length()).map { arr.getString(it) } },
            env = optJSONObject("env")?.toStringMap(),
        )
        McpServerType.http, McpServerType.sse -> McpServerConfig(
            type = type,
            url = optString("url").ifEmpty { null },
            headers = optJSONObject("headers")?.toStringMap(),
        )
    }
}

fun McpServerConfig.toJsonObject(): JSONObject = JSONObject().also { obj ->
    obj.put("type", type.name)
    command?.let { obj.put("command", it) }
    args?.let { list ->
        val arr = JSONArray()
        list.forEach { arr.put(it) }
        obj.put("args", arr)
    }
    env?.let { obj.put("env", it.toStringJsonObject()) }
    url?.let { obj.put("url", it) }
    headers?.let { obj.put("headers", it.toStringJsonObject()) }
}

fun JSONObject.toMcpServersMap(): Map<String, McpServerConfig> =
    keys().asSequence().associateWith { key -> getJSONObject(key).toMcpServerConfig() }

fun Map<String, McpServerConfig>.toMcpServersJsonObject(): JSONObject =
    JSONObject().also { obj -> forEach { (name, config) -> obj.put(name, config.toJsonObject()) } }

// --- Draft <-> Config conversion ---

fun McpServerConfig.toDraft(name: String): McpServerDraft = McpServerDraft(
    name = name,
    type = type,
    command = command ?: "",
    argsText = args?.joinToString("\n") ?: "",
    env = env?.entries?.map { it.key to it.value } ?: emptyList(),
    url = url ?: "",
    headers = headers?.entries?.map { it.key to it.value } ?: emptyList(),
)

fun Map<String, McpServerConfig>.toDraftList(): List<McpServerDraft> =
    entries.map { (name, config) -> config.toDraft(name) }

fun McpServerDraft.toConfig(): McpServerConfig = when (type) {
    McpServerType.stdio -> McpServerConfig(
        type = type,
        command = command.trim().ifEmpty { null },
        args = argsText.split("\n").map { it.trim() }.filter { it.isNotEmpty() }.ifEmpty { null },
        env = env.filter { it.first.isNotEmpty() }
            .associate { it.first to it.second }
            .ifEmpty { null },
    )
    McpServerType.http, McpServerType.sse -> McpServerConfig(
        type = type,
        url = url.trim().ifEmpty { null },
        headers = headers.filter { it.first.isNotEmpty() }
            .associate { it.first to it.second }
            .ifEmpty { null },
    )
}

fun List<McpServerDraft>.toMcpServersMap(): Map<String, McpServerConfig> =
    associate { it.name.trim() to it.toConfig() }
