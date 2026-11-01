package org.reelcheck.core

import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.roundToInt

enum class Tone { BAD, WARN, INFO, MUTED }

data class VerdictText(val label: String, val tone: Tone, val meaning: String)

/**
 * User-facing wording, kept in step with the website (frontend/lib/present.ts). Plain, public, no internals,
 * and never "real" or "fake": a result describes the footage, not the people who shared it.
 */
object Wording {
    val VERDICTS = mapOf(
        "DEBUNKED" to VerdictText("Debunked", Tone.BAD,
            "Fact-checkers have already reviewed this claim and rated it false or misleading."),
        "LIKELY_OLD_FOOTAGE" to VerdictText("Likely old footage", Tone.WARN,
            "The same or very similar footage was online before the date the reel claims."),
        // Neutral, never green: it is not a "real" stamp.
        "NO_CONTRADICTION_FOUND" to VerdictText("No contradiction found", Tone.INFO,
            "Nothing earlier turned up. That is not proof the reel is real."),
        "UNVERIFIED" to VerdictText("Unverified", Tone.MUTED, "Not enough information to judge either way."),
    )

    private val STEPS = mapOf(
        "downloading" to "Fetching the reel",
        "starting" to "Starting",
        "extracting" to "Pulling frames and audio",
        "transcribing" to "Listening and reading on-screen text",
        "understanding" to "Working out what the reel claims",
        "searching" to "Searching for earlier copies and fact-checks",
        "comparing" to "Comparing the evidence",
        "done" to "Report ready",
    )

    private val SOURCES = mapOf(
        "fact_check" to "Fact-check", "youtube" to "YouTube", "own_index" to "Known footage",
        "vision_web" to "Web image match",
    )

    /** Same threshold as the backend's WEAK_SIMILARITY: below it, frames do not match. */
    const val MATCH_THRESHOLD = 0.8

    const val DISCLAIMER = "Automated check. Not a final judgment."

    fun verdict(code: String): VerdictText = VERDICTS[code] ?: VERDICTS.getValue("UNVERIFIED")

    fun step(progress: Progress): String = when {
        progress.queuePosition != null && progress.queuePosition > 1 ->
            "Waiting in line (${progress.queuePosition - 1} ahead)"
        progress.step == null -> "Waiting to start"
        else -> STEPS[progress.step] ?: "Working"
    }

    fun source(name: String): String = SOURCES[name] ?: "Source"

    fun percent(x: Double): String = "${(x * 100).roundToInt()}%"

    fun confidence(x: Double): String = "Confidence ${percent(x)}" // as on the website

    fun similarity(sim: Double?): String? = when {
        sim == null -> null
        sim >= MATCH_THRESHOLD -> "${percent(sim)} frame match"
        else -> "frames do not match"
    }

    /** "2015-03-02" or an ISO timestamp → "2 Mar 2015". Unparseable input comes back unchanged. */
    fun date(iso: String?): String {
        if (iso.isNullOrBlank()) return ""
        val day = runCatching { LocalDate.parse(iso.take(10)) }.getOrNull() ?: return iso
        return day.format(DateTimeFormatter.ofPattern("d MMM yyyy", Locale.ENGLISH))
    }

    /** One line for the allowance, e.g. "1 free check left today" or "2 earned checks". */
    fun allowance(a: Allowance): String = when {
        a.free_left > 0 && a.ad_credits > 0 -> "${checks(a.free_left)} free today, ${a.ad_credits} earned"
        a.free_left > 0 -> "${checks(a.free_left)} free today"
        a.ad_credits > 0 -> "${a.ad_credits} earned ${if (a.ad_credits == 1) "check" else "checks"}"
        else -> "Today's free check is used" + resets(a.resets_at)
    }

    private fun checks(n: Int) = if (n == 1) "1 check" else "$n checks"

    private fun resets(iso: String, zone: ZoneId = ZoneId.systemDefault()): String {
        val at = runCatching { OffsetDateTime.parse(iso).atZoneSameInstant(zone) }.getOrNull() ?: return ""
        return ". Next one at " + at.format(DateTimeFormatter.ofPattern("h:mm a", Locale.ENGLISH))
    }
}
