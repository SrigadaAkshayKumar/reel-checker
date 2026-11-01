package org.reelcheck.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

/** JSON shapes of the backend (backend/app/api/mobile.py, views.py). Unknown fields are ignored. */
val ApiJson = Json { ignoreUnknownKeys = true; explicitNulls = false; coerceInputValues = true }

@Serializable
data class Allowance(
    val user_id: String = "",
    val free_left: Int = 0,
    val ad_credits: Int = 0,
    val can_check: Boolean = false,
    val can_watch_ad: Boolean = true,
    val resets_at: String = "",
    val ads_enabled: Boolean = false,
)

@Serializable
data class Session(
    val user_id: String,
    val token: String,
    val free_left: Int = 0,
    val ad_credits: Int = 0,
    val can_check: Boolean = false,
    val can_watch_ad: Boolean = true,
    val resets_at: String = "",
    val ads_enabled: Boolean = false,
) {
    fun allowance() = Allowance(user_id, free_left, ad_credits, can_check, can_watch_ad, resets_at, ads_enabled)
}

@Serializable
data class Job(
    val job_id: String,
    val status: String,               // queued | running | done | failed
    val step: String? = null,
    val steps: List<String> = emptyList(),
    val queue_position: Int? = null,
    val error: String? = null,
    val error_code: String? = null,   // need_file | bad_video | error
    val report_id: String? = null,
    val report_url: String? = null,
    val share_url: String? = null,
    val cached: Boolean = false,
    val charged: String? = null,      // free | ad
    val free_left: Int? = null,
    val ad_credits: Int? = null,
) {
    val finished get() = status == "done" || status == "failed"
}

@Serializable
data class Evidence(
    val source: String = "",
    val title: String = "",
    val url: String? = null,
    val date: String? = null,
    val similarity: Double? = null,
    val publisher: String? = null,
    val rating: String? = null,
    val supports: String = "lead",    // debunk | earlier_footage | lead
)

@Serializable
data class Claim(val claim_text: String = "", val language: String = "")

@Serializable
data class Report(
    val report_id: String,
    val created_at: String = "",
    val verdict: String,              // DEBUNKED | LIKELY_OLD_FOOTAGE | NO_CONTRADICTION_FOUND | UNVERIFIED
    val verdict_label: String = "",
    val confidence: Double = 0.0,
    val reasons: List<String> = emptyList(),
    val summary: String = "",
    val summary_local: String = "",
    val claim: Claim = Claim(),
    val evidence: List<Evidence> = emptyList(),
    val partial: Boolean = false,
    val disclaimer: String = "",
    val share_url: String = "",
)

/** `{"detail": {"code", "message", ...}}` or `{"detail": "text"}`. */
@Serializable
internal data class ErrorBody(val detail: JsonElement? = null)

/** An error answer from the backend. [message] is written for the user. */
class ApiException(val status: Int, val code: String, message: String, val adsEnabled: Boolean = false) :
    Exception(message)
