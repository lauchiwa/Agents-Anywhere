package com.agentsanywhere.app.feature.files

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

// Result of a completed download. `uri` is set on API 29+ (MediaStore entry in
// the public Downloads folder); `location` is a human-readable spot to surface
// in a toast/snackbar so the user knows where to find the file.
data class SavedDownload(
    val displayName: String,
    val location: String,
    val uri: Uri?,
)

// Saves a remote binary into the device's Downloads without requiring any
// runtime storage permission:
//   - API 29+ (Q): MediaStore.Downloads -> public Downloads, visible to file
//     managers so the user can tap an APK to install it.
//   - API 26-28: app-specific external dir (getExternalFilesDir), the only
//     zero-permission option pre-scoped-storage. Reports the full path.
class FileDownloadSaver(
    private val context: Context,
    private val filesController: FilesController,
) {
    suspend fun download(
        connectorId: String,
        root: String,
        path: String,
        onProgress: ((bytesRead: Long, total: Long) -> Unit)? = null,
    ): Result<SavedDownload> {
        val info = filesController.prepareDownload(connectorId, root, path)
            .getOrElse { return Result.failure(it) }
        return withContext(Dispatchers.IO) {
            runCatching {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    saveViaMediaStore(info, onProgress)
                } else {
                    saveViaLegacyDir(info, onProgress)
                }
            }
        }
    }

    private suspend fun saveViaMediaStore(
        info: DownloadInfo,
        onProgress: ((Long, Long) -> Unit)?,
    ): SavedDownload {
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, info.name)
            put(MediaStore.Downloads.MIME_TYPE, info.mediaType.ifBlank { "application/octet-stream" })
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val collection = MediaStore.Downloads.EXTERNAL_CONTENT_URI
        val uri = resolver.insert(collection, values)
            ?: throw IllegalStateException("Could not create a Downloads entry.")
        try {
            val sink = resolver.openOutputStream(uri)
                ?: throw IllegalStateException("Could not open the Downloads file for writing.")
            sink.use { out ->
                filesController.streamDownload(info.downloadUrl, out) { read ->
                    onProgress?.invoke(read, info.size)
                }.getOrThrow()
            }
            val done = ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }
            resolver.update(uri, done, null, null)
            return SavedDownload(displayName = info.name, location = "Downloads", uri = uri)
        } catch (error: Throwable) {
            runCatching { resolver.delete(uri, null, null) }
            throw error
        }
    }

    private suspend fun saveViaLegacyDir(
        info: DownloadInfo,
        onProgress: ((Long, Long) -> Unit)?,
    ): SavedDownload {
        val dir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            ?: throw IllegalStateException("External storage is unavailable.")
        if (!dir.exists()) dir.mkdirs()
        val target = uniqueFile(dir, info.name)
        target.outputStream().use { out ->
            filesController.streamDownload(info.downloadUrl, out) { read ->
                onProgress?.invoke(read, info.size)
            }.getOrThrow()
        }
        return SavedDownload(displayName = target.name, location = target.absolutePath, uri = null)
    }

    private fun uniqueFile(dir: File, name: String): File {
        val base = File(dir, name)
        if (!base.exists()) return base
        val dot = name.lastIndexOf('.')
        val stem = if (dot > 0) name.substring(0, dot) else name
        val ext = if (dot > 0) name.substring(dot) else ""
        var index = 1
        while (true) {
            val candidate = File(dir, "$stem ($index)$ext")
            if (!candidate.exists()) return candidate
            index++
        }
    }
}
