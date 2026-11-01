package org.reelcheck.app

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import org.reelcheck.core.Allowance
import org.reelcheck.core.CheckInput
import org.reelcheck.core.Outcome
import org.reelcheck.core.Report
import org.reelcheck.core.Wording

sealed interface CheckState {
    data object Idle : CheckState
    data class Working(val text: String) : CheckState
    data class Done(val report: Report, val cached: Boolean) : CheckState
    /** Out of checks: [canWatch] false when ads are off on the server or the user holds the maximum. */
    data class NeedAd(val message: String, val canWatch: Boolean, val note: String? = null) : CheckState
    data class NeedFile(val message: String) : CheckState
    data class Error(val message: String) : CheckState
}

/**
 * Runs checks for one screen (the app or the floating button) and keeps their state. The flow from the
 * build guide: free check → "watch an ad" → ad → wait for the server's credit → run the same check again.
 */
class CheckController(private val context: Context, private val scope: CoroutineScope) {
    private val app = context.reel
    private val _state = MutableStateFlow<CheckState>(CheckState.Idle)
    val state: StateFlow<CheckState> = _state
    private val _allowance = MutableStateFlow<Allowance?>(null)
    val allowance: StateFlow<Allowance?> = _allowance

    private var last: CheckInput? = null
    private var running: Job? = null

    fun refreshAllowance() {
        scope.launch { _allowance.value = runCatching { app.checker.allowance() }.getOrNull() ?: _allowance.value }
    }

    fun check(input: CheckInput) {
        if (input != last) (last as? CheckInput.Video)?.let { Videos.discard(it.video) }
        last = input
        running?.cancel()
        running = scope.launch {
            _state.value = CheckState.Working("Starting")
            val outcome = app.checker.run(input) { _state.value = CheckState.Working(Wording.step(it)) }
            _state.value = when (outcome) {
                is Outcome.Done -> CheckState.Done(outcome.report, outcome.cached).also { forget() }
                is Outcome.NeedAd -> needAd(outcome.message, outcome.adsEnabled)
                is Outcome.NeedFile -> CheckState.NeedFile(outcome.message).also { forget() }
                is Outcome.Failed -> CheckState.Error(outcome.message)
            }
            refreshAllowance()
        }
    }

    /** "Watch a short ad to run another check". Never grants anything itself: the server does. */
    fun watchAdAndRetry() {
        val input = last ?: return
        running?.cancel()
        running = scope.launch {
            val before = runCatching { app.checker.allowance().ad_credits }.getOrDefault(0)
            _state.value = CheckState.Working("Loading the ad")
            when (Ads.show(context)) {
                AdResult.NO_AD -> _state.value = needAd(NO_AD, true, "No ad is available right now. Try again in a minute.")
                AdResult.CLOSED_EARLY -> _state.value = needAd(CLOSED, true, "The ad was closed before the end.")
                AdResult.REWARDED -> {
                    _state.value = CheckState.Working("Adding your check")
                    if (app.checker.waitForCredit(before)) {
                        check(input)
                    } else {
                        _state.value = CheckState.Error("Your check hasn't arrived yet. Try again in a minute; " +
                            "it is kept for you.")
                    }
                }
            }
            refreshAllowance()
        }
    }

    /** Retry the last check (after an error). */
    fun retry() {
        last?.let { check(it) }
    }

    fun reset() {
        running?.cancel()
        forget()
        _state.value = CheckState.Idle
    }

    fun feedback(report: Report, correct: Boolean) {
        scope.launch { runCatching { app.api.feedback(report.report_id, correct) } }
    }

    private fun needAd(message: String, adsEnabled: Boolean, note: String? = null): CheckState.NeedAd {
        val canWatch = adsEnabled && (_allowance.value?.can_watch_ad ?: true)
        val text = if (adsEnabled) message else "You've used today's free check. Come back tomorrow for another."
        return CheckState.NeedAd(text, canWatch, note)
    }

    private fun forget() {
        (last as? CheckInput.Video)?.let { Videos.discard(it.video) }
        last = null
    }

    private companion object {
        const val NO_AD = "You've used today's free check. Watch a short ad to run another check."
        const val CLOSED = NO_AD
    }
}
