package org.reelcheck.app

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.reelcheck.core.VideoFile
import java.io.File
import java.io.IOException

object Videos {
    const val MAX_BYTES = 50L * 1024 * 1024 // backend MAX_UPLOAD_MB
    private val EXTENSIONS = setOf("mp4", "mov", "m4v", "webm", "mkv", "3gp")

    class TooBig : IOException("The video is larger than 50 MB. Trim it, or record a shorter part.")

    /**
     * Copies a shared or picked video into the app's cache for upload (a content Uri can't be re-read
     * later). Delete it after the check with [discard].
     */
    suspend fun copy(context: Context, uri: Uri): VideoFile = withContext(Dispatchers.IO) {
        val resolver = context.contentResolver
        var name = "reel.mp4"
        resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                c.getString(0)?.let { name = it }
                if (!c.isNull(1) && c.getLong(1) > MAX_BYTES) throw TooBig()
            }
        }
        val ext = name.substringAfterLast('.', "").lowercase()
        if (ext !in EXTENSIONS) {
            name = "reel." + when (resolver.getType(uri)) {
                "video/quicktime" -> "mov"
                "video/webm" -> "webm"
                "video/3gpp" -> "3gp"
                else -> "mp4"
            }
        }
        val dir = File(context.cacheDir, "uploads").apply { mkdirs() }
        val out = File.createTempFile("reel", "." + name.substringAfterLast('.'), dir)
        try {
            val input = resolver.openInputStream(uri) ?: throw IOException("Can't open this video.")
            input.use { src ->
                out.outputStream().use { dst ->
                    val buf = ByteArray(1 shl 16)
                    var total = 0L
                    while (true) {
                        val n = src.read(buf)
                        if (n < 0) break
                        total += n
                        if (total > MAX_BYTES) throw TooBig()
                        dst.write(buf, 0, n)
                    }
                }
            }
        } catch (e: IOException) {
            out.delete()
            throw e
        }
        VideoFile(out, name)
    }

    fun discard(video: VideoFile?) {
        video?.file?.delete()
    }
}
