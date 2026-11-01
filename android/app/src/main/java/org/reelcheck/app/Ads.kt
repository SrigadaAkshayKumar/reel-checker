package org.reelcheck.app

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Bundle
import com.google.android.gms.ads.AdError
import com.google.android.gms.ads.AdRequest
import com.google.android.gms.ads.FullScreenContentCallback
import com.google.android.gms.ads.LoadAdError
import com.google.android.gms.ads.rewarded.RewardedAd
import com.google.android.gms.ads.rewarded.RewardedAdLoadCallback
import com.google.android.gms.ads.rewarded.ServerSideVerificationOptions
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch

/** How a rewarded ad ended. A reward here is only a hint: the credit comes from Google's call to our server. */
enum class AdResult { REWARDED, CLOSED_EARLY, NO_AD }

object Ads {
    private var pending: CompletableDeferred<AdResult>? = null

    /**
     * Shows one rewarded ad in [AdActivity] (works from the app and from the floating button's service)
     * and waits until it closes.
     */
    suspend fun show(context: Context): AdResult {
        pending?.complete(AdResult.NO_AD)
        val result = CompletableDeferred<AdResult>().also { pending = it }
        context.startActivity(Intent(context, AdActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        return result.await()
    }

    internal fun finish(result: AdResult) {
        pending?.complete(result)
        pending = null
    }
}

/** Transparent activity that loads and shows a rewarded ad, then closes (the user lands back where they were). */
class AdActivity : Activity() {
    private var earned = false
    private var done = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val app = reel
        app.scope.launch {
            // The SSV user id tells our server whose account gets the credit.
            val userId = runCatching { app.checker.token(); app.prefs.userId }.getOrNull()
            if (userId == null) return@launch close(AdResult.NO_AD)
            RewardedAd.load(this@AdActivity, BuildConfig.ADMOB_REWARDED_ID, AdRequest.Builder().build(),
                object : RewardedAdLoadCallback() {
                    override fun onAdLoaded(ad: RewardedAd) = show(ad, userId)
                    override fun onAdFailedToLoad(error: LoadAdError) = close(AdResult.NO_AD)
                })
        }
    }

    private fun show(ad: RewardedAd, userId: String) {
        if (isFinishing) return close(AdResult.NO_AD)
        ad.setServerSideVerificationOptions(ServerSideVerificationOptions.Builder().setUserId(userId).build())
        ad.fullScreenContentCallback = object : FullScreenContentCallback() {
            override fun onAdDismissedFullScreenContent() =
                close(if (earned) AdResult.REWARDED else AdResult.CLOSED_EARLY)
            override fun onAdFailedToShowFullScreenContent(error: AdError) = close(AdResult.NO_AD)
        }
        ad.show(this) { earned = true }
    }

    private fun close(result: AdResult) {
        if (done) return
        done = true
        Ads.finish(result)
        finish()
    }

    override fun onDestroy() {
        close(AdResult.CLOSED_EARLY) // no-op if already closed
        super.onDestroy()
    }
}
