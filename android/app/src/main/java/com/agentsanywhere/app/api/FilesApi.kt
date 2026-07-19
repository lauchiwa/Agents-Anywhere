package com.agentsanywhere.app.api

import org.json.JSONObject

class FilesApi(
    private val client: ApiClient = ApiClient(),
) {
    fun listFiles(
        serverUrl: String,
        authorizationToken: String,
        deviceId: String,
        root: String,
        path: String = ".",
    ): RemoteDirectory {
        val body = JSONObject().apply {
            put("root", root)
            put("path", path)
        }
        val response = client.postJson(
            serverUrl = serverUrl,
            path = "/connectors/${deviceId.urlEncode()}/fs/list",
            body = body,
            authorizationToken = authorizationToken,
        )
        val result = response.optJSONObject("result") ?: JSONObject()
        return RemoteDirectory(
            path = result.optString("path", root).ifBlank { root },
            entries = result.optJSONArray("entries").toObjectList { toRemoteDirectoryEntry() },
            truncated = result.optBoolean("truncated", false),
        )
    }

    fun readTextFile(
        serverUrl: String,
        authorizationToken: String,
        deviceId: String,
        root: String,
        path: String,
        maxBytes: Int = 1_048_576,
    ): RemoteTextFile {
        val body = JSONObject().apply {
            put("path", path)
            put("maxBytes", maxBytes)
        }
        return client.postJson(
            serverUrl = serverUrl,
            path = "/connectors/${deviceId.urlEncode()}/fs/readText?root=${root.urlEncode()}",
            body = body,
            authorizationToken = authorizationToken,
        ).toRemoteTextFile()
    }

    // Step 1 of a binary download: ask the server to stage the file and hand
    // back a tokenized transfer URL. Stream the actual bytes with
    // ApiClient.downloadToStream(serverUrl, download.downloadUrl, token, sink).
    fun prepareDownload(
        serverUrl: String,
        authorizationToken: String,
        deviceId: String,
        root: String,
        path: String,
    ): RemoteDownload {
        val body = JSONObject().apply { put("path", path) }
        val response = client.postJson(
            serverUrl = serverUrl,
            path = "/connectors/${deviceId.urlEncode()}/fs/read?root=${root.urlEncode()}",
            body = body,
            authorizationToken = authorizationToken,
        )
        val result = response.optJSONObject("result") ?: JSONObject()
        val downloadUrl = result.optString("downloadUrl", "")
        if (downloadUrl.isBlank()) {
            throw ApiException("Server did not return a download URL.")
        }
        val fallbackName = path.trimEnd('/').substringAfterLast('/').ifBlank { "download" }
        return RemoteDownload(
            name = result.optString("name", fallbackName).ifBlank { fallbackName },
            size = if (result.has("size") && !result.isNull("size")) result.optLong("size") else 0L,
            mediaType = result.optString("mediaType", "application/octet-stream")
                .ifBlank { "application/octet-stream" },
            downloadUrl = downloadUrl,
        )
    }

    // Step 2 of a binary download: stream the staged transfer bytes into sink.
    fun downloadTransfer(
        serverUrl: String,
        authorizationToken: String,
        downloadUrl: String,
        sink: java.io.OutputStream,
        onProgress: ((bytesRead: Long) -> Unit)? = null,
    ): Long {
        return client.downloadToStream(
            serverUrl = serverUrl,
            path = downloadUrl,
            authorizationToken = authorizationToken,
            sink = sink,
            onProgress = onProgress,
        )
    }

    private fun JSONObject.toRemoteDirectoryEntry(): RemoteDirectoryEntry {
        return RemoteDirectoryEntry(
            name = optString("name", "Untitled").ifBlank { "Untitled" },
            path = optString("path", ""),
            type = optString("type", "other"),
            size = if (has("size") && !isNull("size")) optLong("size") else null,
        )
    }

    private fun JSONObject.toRemoteTextFile(): RemoteTextFile {
        return RemoteTextFile(
            path = optString("path", ""),
            name = optString("name", "Untitled").ifBlank { "Untitled" },
            size = optLong("size", 0L),
            sha256 = optString("sha256", ""),
            encoding = optString("encoding", "utf8"),
            content = optString("content", ""),
            truncated = optBoolean("truncated", false),
            binary = optBoolean("binary", false),
            serverTime = optString("serverTime", ""),
        )
    }
}
