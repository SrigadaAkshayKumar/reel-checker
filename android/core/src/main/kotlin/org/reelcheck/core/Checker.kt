package org.reelcheck.core

import kotlinx.coroutines.delay

/** Where the app keeps its anonymous account. The token is the only secret. */
interface TokenStore {
    var token: String?
    var userId: String?
}

/** What the user asked to check. */
sealed interface CheckInput {
    data class Link(val url: String) : CheckInput
    data class Video(val video: VideoFile) : CheckInput
}

/** How a check ended. */
sealed interface Outcome {
    data class Done(val report: Report, val cached: Boolean) : Outcome
    /** No free check or credit left: offer a rewarded ad (if [adsEnabled]). */
    data class NeedAd(val message: String, val adsEnabled: Boolean) : Outcome
    /** The link could not be fetched: ask for the video file. The check was refunded. */
    data class NeedFile(val message: String) : Outcome
    data class Failed(val message: String) : Outcome
}

/** Progress for the UI: a step name from the backend (see [Wording.step]) or a queue position. */
data class Progress(val step: String?, val queuePosition: Int?, val steps: List<String>)

/**
 * One check, start to finish: make sure there is an account, submit, poll the job, fetch the report.
 * Shared by the app screen and the floating button. The server decides what a check costs.
 */
class Checker(
    private val api: ReelApi,
    private val store: TokenStore,
    private val pollMillis: Long = 1500,
    private val maxPolls: Int = 400, // 10 minutes: long queues on a busy day
) {
    /** The account token, creating an anonymous account on first use. */
    suspend fun token(): String = store.token ?: newSession().token

    suspend fun allowance(): Allowance = authed { api.me(it) }

    suspend fun run(input: CheckInput, caption: String = "", onProgress: (Progress) -> Unit = {}): Outcome {
        val job = try {
            authed { token ->
                when (input) {
                    is CheckInput.Link -> api.checkLink(token, input.url, caption)
                    is CheckInput.Video -> api.checkFile(token, input.video, caption)
                }
            }
        } catch (e: ApiException) {
            return when (e.code) {
                "watch_ad" -> Outcome.NeedAd(e.message ?: "", e.adsEnabled)
                "need_file" -> Outcome.NeedFile(e.message ?: "")
                else -> Outcome.Failed(e.message ?: "")
            }
        }
        return follow(job, onProgress)
    }

    /** After a rewarded ad: Google tells the server, not the app, so wait for the credit to arrive. */
    suspend fun waitForCredit(before: Int, tries: Int = 4, waitMillis: Long = 2000): Boolean {
        repeat(tries) {
            delay(waitMillis)
            val now = runCatching { allowance() }.getOrNull() ?: return@repeat
            if (now.ad_credits > before) return true
        }
        return false
    }

    private suspend fun follow(first: Job, onProgress: (Progress) -> Unit): Outcome {
        var job = first
        var polls = 0
        var networkErrors = 0
        while (!job.finished) {
            onProgress(Progress(job.step, job.queue_position, job.steps))
            if (++polls > maxPolls) return Outcome.Failed("This is taking much longer than usual. Try again later.")
            delay(pollMillis)
            job = try {
                api.job(job.job_id).also { networkErrors = 0 }
            } catch (e: ApiException) {
                if (e.status != 0 || ++networkErrors > 5) return Outcome.Failed(e.message ?: "")
                continue // a dropped mobile connection: keep polling
            }
        }
        if (job.status == "failed") {
            val message = job.error ?: "The check failed. Please try again."
            return if (job.error_code == "need_file") Outcome.NeedFile(message) else Outcome.Failed(message)
        }
        val reportUrl = job.report_url ?: return Outcome.Failed("The report is missing. Please try again.")
        return try {
            Outcome.Done(api.report(reportUrl), job.cached)
        } catch (e: ApiException) {
            Outcome.Failed(e.message ?: "")
        }
    }

    private suspend fun newSession(): Session = api.createSession().also {
        store.token = it.token
        store.userId = it.user_id
    }

    /** Runs [block] with a token; a 401 means the account is gone (new server, wiped data): sign in again once. */
    private suspend fun <T> authed(block: suspend (String) -> T): T = try {
        block(token())
    } catch (e: ApiException) {
        if (e.status != 401) throw e
        block(newSession().token)
    }
}
