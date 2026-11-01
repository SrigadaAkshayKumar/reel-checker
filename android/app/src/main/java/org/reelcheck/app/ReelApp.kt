package org.reelcheck.app

import android.app.Application
import android.content.Context
import com.google.android.gms.ads.MobileAds
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.reelcheck.core.Checker
import org.reelcheck.core.ReelApi
import org.reelcheck.core.TokenStore

/** App-wide objects. The screen and the floating button share one account and one client. */
class ReelApp : Application() {
    lateinit var prefs: Prefs
        private set
    lateinit var api: ReelApi
        private set
    lateinit var checker: Checker
        private set
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        api = ReelApi(BuildConfig.API_URL)
        checker = Checker(api, prefs)
        // Off the main thread: the Ads SDK's start-up is slow.
        scope.launch(Dispatchers.IO) { MobileAds.initialize(this@ReelApp) {} }
    }
}

val Context.reel: ReelApp get() = applicationContext as ReelApp

/**
 * The anonymous account and settings, in app-private storage. The token only identifies an anonymous
 * account with a few check credits, so it is not worth hardware-backed encryption; it is excluded from
 * backups (allowBackup=false) so it never leaves the phone.
 */
class Prefs(context: Context) : TokenStore {
    private val sp = context.getSharedPreferences("reel", Context.MODE_PRIVATE)

    override var token: String?
        get() = sp.getString("token", null)
        set(value) = sp.edit().putString("token", value).apply()

    override var userId: String?
        get() = sp.getString("user_id", null)
        set(value) = sp.edit().putString("user_id", value).apply()

    /** Show the floating button everywhere, not only over Instagram (when usage access is off). */
    var alwaysShowDot: Boolean
        get() = sp.getBoolean("always_show_dot", false)
        set(value) = sp.edit().putBoolean("always_show_dot", value).apply()

    var dotX: Int
        get() = sp.getInt("dot_x", -1)
        set(value) = sp.edit().putInt("dot_x", value).apply()

    var dotY: Int
        get() = sp.getInt("dot_y", 300)
        set(value) = sp.edit().putInt("dot_y", value).apply()
}
