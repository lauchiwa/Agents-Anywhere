package com.agentsanywhere.app.api

import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit

class ApiClient {
    companion object {
        // Shared client for SSE streams. One instance reuses OkHttp's
        // connection pool instead of leaking a socket per reconnect.
        //
        // readTimeout is 40s, NOT 0. The server sends a `: keepalive` comment
        // every 15s, so a healthy stream never idles longer than that — 40s
        // leaves generous margin so normal quiet gaps don't trip it. Crucially,
        // a *half-dead* connection (TCP still open but the server's pushes no
        // longer arrive — common after NAT rebinding / network handoff) stops
        // delivering keepalives; with readTimeout=0 the client would block on
        // readLine() forever, silently missing every update. With 40s the read
        // throws SocketTimeoutException, the caller's loop reconnects, and the
        // stream self-heals. (readTimeout=0 was the bug behind "updates stop
        // arriving until you kill the app".)
        private val sseClient: OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(40, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }

    fun getJson(
        serverUrl: String,
        path: String,
        authorizationToken: String? = null,
    ): JSONObject {
        return requestJson(
            serverUrl = serverUrl,
            path = path,
            method = "GET",
            body = null,
            authorizationToken = authorizationToken,
        )
    }

    fun postJson(
        serverUrl: String,
        path: String,
        body: JSONObject,
        authorizationToken: String? = null,
    ): JSONObject {
        return requestJson(
            serverUrl = serverUrl,
            path = path,
            method = "POST",
            body = body,
            authorizationToken = authorizationToken,
        )
    }

    fun patchJson(
        serverUrl: String,
        path: String,
        body: JSONObject,
        authorizationToken: String? = null,
    ): JSONObject {
        return requestJson(
            serverUrl = serverUrl,
            path = path,
            method = "PATCH",
            body = body,
            authorizationToken = authorizationToken,
        )
    }

    fun putJson(
        serverUrl: String,
        path: String,
        body: JSONObject,
        authorizationToken: String? = null,
    ): JSONObject {
        return requestJson(
            serverUrl = serverUrl,
            path = path,
            method = "PUT",
            body = body,
            authorizationToken = authorizationToken,
        )
    }

    fun deleteJson(
        serverUrl: String,
        path: String,
        authorizationToken: String? = null,
    ): JSONObject {
        return requestJson(
            serverUrl = serverUrl,
            path = path,
            method = "DELETE",
            body = null,
            authorizationToken = authorizationToken,
        )
    }

    fun streamSse(
        serverUrl: String,
        path: String,
        onOpen: () -> Unit = {},
        onStart: (Call) -> Unit = {},
        onEvent: (JSONObject) -> Unit,
    ) {
        // SSE must ride a long-lived connection: the server keeps it open and
        // sends a `: keepalive` comment every 15s. HttpURLConnection handled
        // this poorly — its read timeout / connection-reuse heuristics made
        // readLine() return null within ~1s (a false end-of-stream), so the
        // caller's reconnect loop hammered the server ~1/s and, combined with
        // per-reconnect full /state pulls, exhausted the client's connection
        // pool until the app had to be killed. OkHttp fixes the reconnect storm.
        //
        // Cancellation: readLine() below is a BLOCKING socket read. A coroutine
        // job.cancel() does NOT interrupt it, so when the user leaves the screen
        // the read would keep the socket pinned and leak it. The `onStart(call)`
        // callback hands the OkHttp Call to the caller so its awaitClose can
        // invoke call.cancel(), which force-closes the socket and unblocks the
        // read immediately. Without this, every screen re-entry leaked one
        // stuck stream — enough of them reproduced the original hang.
        val endpoint = "${serverUrl.trimEnd('/')}$path"
        val request = Request.Builder()
            .url(endpoint)
            .header("Accept", "text/event-stream")
            .header("Cache-Control", "no-cache")
            .header("ngrok-skip-browser-warning", "true")
            .build()
        val call = sseClient.newCall(request)
        onStart(call)
        try {
            call.execute().use { response ->
                if (!response.isSuccessful) {
                    val responseText = response.body?.string().orEmpty()
                    throw ApiException(
                        message = parseErrorMessage(responseText) ?: defaultErrorMessage(response.code),
                        statusCode = response.code,
                    )
                }
                onOpen()
                val reader = response.body?.charStream()?.buffered()
                    ?: throw ApiException("Session stream returned an empty body.")
                val data = StringBuilder()
                // readLine() blocks until a full line arrives or the stream
                // closes (returns null). Thread interruption from the caller's
                // job.cancel() closes the socket, which unblocks this read.
                while (!Thread.currentThread().isInterrupted) {
                    val line = reader.readLine() ?: break
                    when {
                        line.isEmpty() -> {
                            if (data.isNotEmpty()) {
                                onEvent(JSONObject(data.toString()))
                                data.clear()
                            }
                        }
                        line.startsWith("data:") -> {
                            if (data.isNotEmpty()) data.append('\n')
                            data.append(line.removePrefix("data:").trimStart())
                        }
                        // Lines starting with ':' are SSE comments (keepalives) —
                        // ignore them; their only job is to keep the socket warm.
                    }
                }
            }
        } catch (exc: ApiException) {
            throw exc
        } catch (exc: IOException) {
            throw ApiException("Could not reach the server. Check the URL and network.", cause = exc)
        } finally {
            call.cancel()
        }
    }

    fun postMultipart(
        serverUrl: String,
        path: String,
        files: List<UploadFilePart>,
        authorizationToken: String? = null,
    ): JSONObject {
        return try {
            val endpoint = URL("${serverUrl.trimEnd('/')}$path")
            val boundary = "AA-${System.currentTimeMillis()}"
            val connection = (endpoint.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 10_000
                readTimeout = 60_000
                doOutput = true
                setRequestProperty("Accept", "application/json")
                setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                setRequestProperty("ngrok-skip-browser-warning", "true")
                if (!authorizationToken.isNullOrBlank()) {
                    setRequestProperty("Authorization", "Bearer $authorizationToken")
                }
            }
            try {
                connection.outputStream.use { output ->
                    files.forEach { file ->
                        output.write("--$boundary\r\n".toByteArray(Charsets.UTF_8))
                        output.write(
                            "Content-Disposition: form-data; name=\"files\"; filename=\"${file.name.httpQuoted()}\"\r\n"
                                .toByteArray(Charsets.UTF_8),
                        )
                        output.write("Content-Type: ${file.mediaType.ifBlank { "application/octet-stream" }}\r\n\r\n".toByteArray(Charsets.UTF_8))
                        output.write(file.bytes)
                        output.write("\r\n".toByteArray(Charsets.UTF_8))
                    }
                    output.write("--$boundary--\r\n".toByteArray(Charsets.UTF_8))
                }
                val responseCode = connection.responseCode
                val responseText = readResponseText(connection, responseCode)
                if (responseCode !in 200..299) {
                    throw ApiException(
                        message = parseErrorMessage(responseText) ?: defaultErrorMessage(responseCode),
                        statusCode = responseCode,
                    )
                }
                if (responseText.isBlank()) JSONObject() else JSONObject(responseText)
            } finally {
                connection.disconnect()
            }
        } catch (exc: ApiException) {
            throw exc
        } catch (exc: IOException) {
            throw ApiException("Could not reach the server. Check the URL and network.", cause = exc)
        }
    }

    fun downloadToStream(
        serverUrl: String,
        path: String,
        authorizationToken: String?,
        sink: java.io.OutputStream,
        onProgress: ((bytesRead: Long) -> Unit)? = null,
    ): Long {
        return try {
            val endpoint = URL("${serverUrl.trimEnd('/')}$path")
            val connection = (endpoint.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 15_000
                // Large binaries (e.g. APKs) stream over a single connection;
                // give each chunk read a generous window before timing out.
                readTimeout = 120_000
                setRequestProperty("Accept", "application/octet-stream")
                setRequestProperty("ngrok-skip-browser-warning", "true")
                if (!authorizationToken.isNullOrBlank()) {
                    setRequestProperty("Authorization", "Bearer $authorizationToken")
                }
            }
            try {
                val responseCode = connection.responseCode
                if (responseCode !in 200..299) {
                    val errorText = connection.errorStream
                        ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
                    throw ApiException(
                        message = parseErrorMessage(errorText) ?: defaultErrorMessage(responseCode),
                        statusCode = responseCode,
                    )
                }
                var total = 0L
                connection.inputStream.use { input ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        sink.write(buffer, 0, read)
                        total += read
                        onProgress?.invoke(total)
                    }
                }
                sink.flush()
                total
            } finally {
                connection.disconnect()
            }
        } catch (exc: ApiException) {
            throw exc
        } catch (exc: IOException) {
            throw ApiException("Could not reach the server. Check the URL and network.", cause = exc)
        }
    }

    private fun requestJson(
        serverUrl: String,
        path: String,
        method: String,
        body: JSONObject?,
        authorizationToken: String?,
    ): JSONObject {
        return try {
            val endpoint = URL("${serverUrl.trimEnd('/')}$path")
            val bodyText = body?.toString()

            val connection = (endpoint.openConnection() as HttpURLConnection).apply {
                requestMethod = method
                connectTimeout = 10_000
                readTimeout = 15_000
                doOutput = bodyText != null
                setRequestProperty("Accept", "application/json")
                setRequestProperty("ngrok-skip-browser-warning", "true")
                if (bodyText != null) {
                    setRequestProperty("Content-Type", "application/json")
                }
                if (!authorizationToken.isNullOrBlank()) {
                    setRequestProperty("Authorization", "Bearer $authorizationToken")
                }
            }

            try {
                if (bodyText != null) {
                    connection.outputStream.use { output ->
                        output.write(bodyText.toByteArray(Charsets.UTF_8))
                    }
                }

                val responseCode = connection.responseCode
                val responseText = readResponseText(connection, responseCode)
                if (responseCode !in 200..299) {
                    throw ApiException(
                        message = parseErrorMessage(responseText) ?: defaultErrorMessage(responseCode),
                        statusCode = responseCode,
                    )
                }

                if (responseText.isBlank()) JSONObject() else JSONObject(responseText)
            } finally {
                connection.disconnect()
            }
        } catch (exc: ApiException) {
            throw exc
        } catch (exc: IOException) {
            throw ApiException("Could not reach the server. Check the URL and network.", cause = exc)
        }
    }

    private fun readResponseText(connection: HttpURLConnection, responseCode: Int): String {
        val stream = if (responseCode in 200..299) {
            connection.inputStream
        } else {
            connection.errorStream
        }
        return stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
    }

    private fun parseErrorMessage(responseText: String): String? {
        return runCatching {
            val detail = JSONObject(responseText).opt("detail")
            when (detail) {
                is String -> detail.takeIf { it.isNotBlank() }
                is JSONObject -> detail.optString("message")
                    .ifBlank { detail.optString("code") }
                    .takeIf { it.isNotBlank() }
                else -> detail?.toString()?.takeIf { it.isNotBlank() }
            }
        }.getOrNull()
    }

    private fun defaultErrorMessage(statusCode: Int): String {
        return when (statusCode) {
            401 -> "Unauthorized request."
            404 -> "Endpoint was not found on this server."
            else -> "Request failed with status $statusCode."
        }
    }

    private fun String.httpQuoted(): String {
        return replace("\\", "\\\\").replace("\"", "\\\"").replace("\r", "").replace("\n", "")
    }
}

data class UploadFilePart(
    val name: String,
    val mediaType: String,
    val bytes: ByteArray,
)

class ApiException(
    override val message: String,
    val statusCode: Int? = null,
    cause: Throwable? = null,
) : Exception(message, cause)
