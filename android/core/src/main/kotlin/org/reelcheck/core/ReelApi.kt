package org.reelcheck.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.buildJsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

/** A video to upload: a local copy plus the name to send (the backend checks the extension). */
data class VideoFile(val file: File, val name: String)

/**
 * HTTP client for the backend (docs/mobile-api.md). Blocking OkHttp calls run on [Dispatchers.IO].
 * Errors become [ApiException] with a user-facing message; a network failure is status 0.
 */
class ReelApi(
    baseUrl: String,
    private val client: OkHttpClient = defaultClient(),
) {
    val baseUrl = baseUrl.trimEnd('/')

    suspend fun createSession(): Session = call(post("/api/app/session", ByteArray(0).toRequestBody()), null)

    suspend fun me(token: String): Allowance = call(get("/api/app/me"), token)

    suspend fun checkLink(token: String, url: String, caption: String = ""): Job =
        call(post("/api/app/check", form { addFormDataPart("url", url).caption(caption) }), token)

    suspend fun checkFile(token: String, video: VideoFile, caption: String = ""): Job =
        call(post("/api/app/check", form {
            addFormDataPart("file", video.name, video.file.asRequestBody(VIDEO))
            caption(caption)
        }), token)

    suspend fun job(jobId: String): Job = call(get("/api/jobs/$jobId"), null)

    suspend fun report(reportUrl: String): Report = call(get(reportUrl), null)

    suspend fun feedback(reportId: String, correct: Boolean, note: String = "") {
        val body = buildJsonObject { put("correct", correct); put("note", note) }.toString()
        call<JsonObject>(post("/api/reports/$reportId/feedback", body.toRequestBody(JSON)), null)
    }

    /** Absolute URL for a backend path such as /api/reports/x/files/compare_1.jpg. */
    fun absolute(path: String) = if (path.startsWith("http")) path else baseUrl + path

    private fun get(path: String) = Request.Builder().url(absolute(path)).get()

    private fun post(path: String, body: RequestBody) = Request.Builder().url(absolute(path)).post(body)

    private fun form(build: MultipartBody.Builder.() -> Unit): RequestBody =
        MultipartBody.Builder().setType(MultipartBody.FORM).apply(build).build()

    private fun MultipartBody.Builder.caption(caption: String) = apply {
        if (caption.isNotBlank()) addFormDataPart("caption", caption.trim())
    }

    private suspend inline fun <reified T> call(request: Request.Builder, token: String?): T =
        withContext(Dispatchers.IO) {
            if (token != null) request.header("Authorization", "Bearer $token")
            val response = try {
                client.newCall(request.build()).execute()
            } catch (e: IOException) {
                throw ApiException(0, "offline", "Can't reach the server. Check your connection and try again.")
            }
            response.use {
                val text = it.body?.string().orEmpty()
                if (!it.isSuccessful) throw problem(it.code, text)
                try {
                    ApiJson.decodeFromString<T>(text)
                } catch (e: IllegalArgumentException) {
                    throw ApiException(it.code, "bad_response", "The server sent an answer this app can't read.")
                }
            }
        }

    companion object {
        private val JSON = "application/json".toMediaType()
        private val VIDEO = "video/*".toMediaType()

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(120, TimeUnit.SECONDS) // uploads of up to 50 MB on a slow connection
            .build()

        internal fun problem(status: Int, text: String): ApiException {
            val detail = runCatching { ApiJson.decodeFromString<ErrorBody>(text).detail }.getOrNull()
            if (detail is JsonObject) {
                val code = detail["code"]?.jsonPrimitive?.contentOrNull ?: "error"
                val message = detail["message"]?.jsonPrimitive?.contentOrNull ?: fallback(status)
                val ads = (detail["ads_enabled"] as? JsonPrimitive)?.booleanOrNull ?: false
                return ApiException(status, code, message, ads)
            }
            val code = if (status == 401) "signed_out" else "error"
            return ApiException(status, code, fallback(status))
        }

        private fun fallback(status: Int) = when (status) {
            404 -> "Not found. The report may have been removed."
            429 -> "Too many checks right now. Try again later."
            in 500..599 -> "The server had a problem. Please try again in a minute."
            else -> "Something went wrong. Please try again."
        }
    }
}
