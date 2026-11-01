package org.reelcheck.app

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.text.InputType
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.reelcheck.core.CheckInput
import org.reelcheck.core.Links
import org.reelcheck.core.Tone
import org.reelcheck.core.Wording
import kotlin.math.abs

/**
 * The floating button over Instagram (build guide, Phase 3). One service, three states in WindowManager
 * overlay windows: a draggable dot (not focusable), an input card and a result card (focusable, so the
 * keyboard and the clipboard work). The X collapses back to the dot; only the notification's Stop ends it.
 * Classic Views, not Compose: Compose in a service window needs extra lifecycle wiring.
 */
class OverlayService : LifecycleService() {
    private lateinit var wm: WindowManager
    private lateinit var checks: CheckController
    private val prefs by lazy { reel.prefs }

    private var dot: View? = null
    private var card: View? = null
    private var cardBody: LinearLayout? = null
    private var input: EditText? = null
    private var dotParams: WindowManager.LayoutParams? = null
    private var lastForeground: String? = null
    private var lastQuery = 0L

    override fun onCreate() {
        super.onCreate()
        wm = getSystemService(WINDOW_SERVICE) as WindowManager
        checks = CheckController(this, lifecycleScope)
        running = true
        lifecycleScope.launch { checks.state.collect { if (cardBody != null) renderResult() } }
        lifecycleScope.launch {
            while (true) {
                updateDotVisibility()
                delay(1000)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        if (intent?.action == ACTION_STOP || !Permissions.canOverlay(this)) {
            stopSelf()
            return START_NOT_STICKY
        }
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notification(), type)
        if (dot == null) showDot()
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        removeCard()
        dot?.let { runCatching { wm.removeView(it) } }
        dot = null
        super.onDestroy()
    }

    // --- the dot ------------------------------------------------------------------------------------

    @SuppressLint("ClickableViewAccessibility") // the tap is handled in the touch listener; drag needs raw events
    private fun showDot() {
        val size = dp(52)
        val view = TextView(this).apply {
            text = "✓"
            gravity = Gravity.CENTER
            setTextColor(0xFFFFFFFF.toInt())
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f)
            background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(BRAND) }
            elevation = dp(6).toFloat()
            contentDescription = "Check this reel"
        }
        val lp = overlayParams(size, size, focusable = false).apply {
            title = "ReelCheck:dot"
            gravity = Gravity.TOP or Gravity.START
            x = if (prefs.dotX >= 0) prefs.dotX else resources.displayMetrics.widthPixels - size - dp(8)
            y = prefs.dotY
        }
        view.setOnTouchListener(object : View.OnTouchListener {
            var startX = 0
            var startY = 0
            var touchX = 0f
            var touchY = 0f
            var moved = false
            override fun onTouch(v: View, e: MotionEvent): Boolean {
                when (e.action) {
                    MotionEvent.ACTION_DOWN -> {
                        startX = lp.x; startY = lp.y; touchX = e.rawX; touchY = e.rawY; moved = false
                    }
                    MotionEvent.ACTION_MOVE -> {
                        if (abs(e.rawX - touchX) > dp(8) || abs(e.rawY - touchY) > dp(8)) moved = true
                        lp.x = startX + (e.rawX - touchX).toInt()
                        lp.y = startY + (e.rawY - touchY).toInt()
                        runCatching { wm.updateViewLayout(v, lp) }
                    }
                    MotionEvent.ACTION_UP -> if (moved) {
                        prefs.dotX = lp.x; prefs.dotY = lp.y
                    } else {
                        v.performClick()
                        openCard()
                    }
                }
                return true
            }
        })
        wm.addView(view, lp)
        dot = view
        dotParams = lp
    }

    private fun updateDotVisibility() {
        val view = dot ?: return
        val show = card == null && (prefs.alwaysShowDot || !Permissions.hasUsageAccess(this) ||
            foregroundApp() in INSTAGRAM)
        view.visibility = if (show) View.VISIBLE else View.GONE
    }

    /** The app on screen, from usage events since the last poll (kept when nothing changed). */
    private fun foregroundApp(): String? {
        val usm = getSystemService(USAGE_STATS_SERVICE) as UsageStatsManager
        val now = System.currentTimeMillis()
        val events = usm.queryEvents(if (lastQuery == 0L) now - 60_000 else lastQuery, now)
        lastQuery = now
        val event = UsageEvents.Event()
        val resumed = if (Build.VERSION.SDK_INT >= 29) UsageEvents.Event.ACTIVITY_RESUMED else 1
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            if (event.eventType == resumed) lastForeground = event.packageName
        }
        return lastForeground
    }

    // --- the cards ----------------------------------------------------------------------------------

    private fun openCard() {
        if (checks.state.value == CheckState.Idle) showInputCard() else showResultCard()
    }

    private fun showInputCard() {
        removeCard()
        val field = EditText(this).apply {
            hint = "Paste the reel link"
            isSingleLine = true
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            imeOptions = EditorInfo.IME_ACTION_GO
            setOnEditorActionListener { _, _, _ -> submit(); true }
        }
        input = field
        val body = column(
            header("Check this reel"),
            text("Copy the reel's link in Instagram (Share → Copy link), then paste it here.", small = true),
            field,
            row(button("Paste", primary = false) { pasteInto(field) }, button("Check") { submit() }),
        )
        showCard(body, height = ViewGroup.LayoutParams.WRAP_CONTENT)
        // Android 10+ lets only the focused app read the clipboard: read it once the card has focus.
        // Then put the cursor in the field with the keyboard up, ready for a long-press paste.
        body.viewTreeObserver.addOnWindowFocusChangeListener { focused ->
            if (!focused) return@addOnWindowFocusChangeListener
            if (field.text.isNullOrBlank()) pasteInto(field, quiet = true)
            if (field.requestFocus()) {
                (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager).showSoftInput(field, 0)
            }
        }
    }

    private fun submit() {
        val link = Links.findReel(input?.text?.toString())
        if (link == null) {
            input?.error = "This doesn't look like an Instagram reel link"
            return
        }
        checks.check(CheckInput.Link(link))
        showResultCard()
    }

    private fun showResultCard() {
        removeCard()
        val body = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        cardBody = body
        val scroll = ScrollView(this).apply { addView(body) }
        showCard(column(header("Reel check"), scroll), height = (resources.displayMetrics.heightPixels * 0.75).toInt())
        renderResult()
    }

    private fun renderResult() {
        val body = cardBody ?: return
        body.removeAllViews()
        val state = checks.state.value
        // Debug builds only: lets the emulator test follow the card (android/ci/emulator_smoke.py).
        if (BuildConfig.DEBUG) Log.d("ReelOverlay", "state ${state::class.simpleName}")
        when (val s = state) {
            CheckState.Idle -> { showInputCard(); return }
            is CheckState.Working -> body.add(row(ProgressBar(this), text(s.text)))
            is CheckState.Done -> {
                val r = s.report
                val v = Wording.verdict(r.verdict)
                body.add(text(v.label, size = 22f, bold = true, color = tone(v.tone)))
                body.add(text(v.meaning, small = true))
                body.add(text(Wording.confidence(r.confidence), bold = true))
                if (r.summary.isNotBlank()) body.add(text(r.summary))
                if (r.summary_local.isNotBlank()) body.add(text(r.summary_local))
                r.evidence.take(3).forEach { e ->
                    body.add(text(e.title.ifBlank { "Source" }, bold = true))
                    body.add(text(listOfNotNull(Wording.source(e.source), Wording.date(e.date).ifBlank { null },
                        Wording.similarity(e.similarity), e.rating).joinToString(" · "), small = true))
                }
                if (r.partial) body.add(text("Some searches could not run, so this may be incomplete.", small = true))
                body.add(text(Wording.DISCLAIMER, small = true))
                if (r.share_url.isNotBlank()) body.add(button("Full report and sources") { open(r.share_url) })
                body.add(row(
                    button("Looks wrong", primary = false) { checks.feedback(r, false); toastLine(body) },
                    button("Check another", primary = false) { checks.reset(); showInputCard() },
                ))
            }
            is CheckState.NeedAd -> {
                body.add(text(s.message))
                s.note?.let { body.add(text(it, small = true)) }
                if (s.canWatch) body.add(button("Watch a short ad to run another check") { checks.watchAdAndRetry() })
            }
            is CheckState.NeedFile -> {
                body.add(text(s.message))
                body.add(button("Open the app to choose the video") {
                    startActivity(Intent(this, MainActivity::class.java)
                        .putExtra(MainActivity.EXTRA_PICK_FILE, true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    checks.reset()
                    collapse()
                })
            }
            is CheckState.Error -> {
                body.add(text(s.message))
                body.add(row(button("Try again") { checks.retry() },
                    button("Check another", primary = false) { checks.reset(); showInputCard() }))
            }
        }
    }

    private fun toastLine(body: LinearLayout) = body.add(text("Thanks, we'll review it.", small = true))

    private fun showCard(content: View, height: Int) {
        val frame = FrameLayout(this).apply {
            background = GradientDrawable().apply { cornerRadius = dp(16).toFloat(); setColor(0xFFFFFFFF.toInt()) }
            elevation = dp(8).toFloat()
            setPadding(dp(16), dp(12), dp(16), dp(16))
            addView(content)
        }
        val lp = overlayParams(resources.displayMetrics.widthPixels - dp(16), height, focusable = true).apply {
            title = "ReelCheck:card"
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            y = dp(16)
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        }
        wm.addView(frame, lp)
        card = frame
        updateDotVisibility()
    }

    private fun collapse() {
        removeCard()
        updateDotVisibility()
    }

    private fun removeCard() {
        card?.let { runCatching { wm.removeView(it) } }
        card = null
        cardBody = null
        input = null
    }

    // --- small view helpers -----------------------------------------------------------------------

    private fun header(title: String) = row(
        text(title, size = 18f, bold = true).apply { layoutParams = LinearLayout.LayoutParams(0, -2, 1f) },
        TextView(this).apply {
            text = "✕"
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
            setPadding(dp(12), dp(4), dp(4), dp(4))
            contentDescription = "Close"
            setOnClickListener { collapse() }
        },
    )

    private fun pasteInto(field: EditText, quiet: Boolean = false) {
        val clip = (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager).primaryClip
        val text = clip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(this)?.toString()
        val link = Links.findReel(text)
        when {
            link != null -> field.setText(link)
            !quiet -> field.error = "The clipboard has no Instagram reel link"
        }
    }

    private fun open(url: String) {
        runCatching {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        collapse()
    }

    private fun text(s: String, size: Float = 15f, bold: Boolean = false, small: Boolean = false, color: Int? = null) =
        TextView(this).apply {
            text = s
            setTextSize(TypedValue.COMPLEX_UNIT_SP, if (small) 13f else size)
            setTextColor(color ?: if (small) 0xFF475467.toInt() else 0xFF101828.toInt())
            if (bold) setTypeface(typeface, Typeface.BOLD)
            setPadding(0, dp(4), 0, dp(4))
        }

    private fun button(label: String, primary: Boolean = true, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        if (primary) {
            setTextColor(0xFFFFFFFF.toInt())
            background = GradientDrawable().apply { cornerRadius = dp(10).toFloat(); setColor(BRAND) }
        }
        setOnClickListener { onClick() }
    }

    private fun column(vararg views: View) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        views.forEach { addView(it) }
    }

    private fun row(vararg views: View) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        views.forEach {
            addView(it)
            (it.layoutParams as? LinearLayout.LayoutParams)?.marginEnd = dp(8)
        }
    }

    private fun LinearLayout.add(v: View) = addView(v)

    private fun tone(t: Tone) = when (t) {
        Tone.BAD -> 0xFFB42318.toInt()
        Tone.WARN -> 0xFFB54708.toInt()
        Tone.INFO -> 0xFF175CD3.toInt()
        Tone.MUTED -> 0xFF475467.toInt()
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun overlayParams(w: Int, h: Int, focusable: Boolean) = WindowManager.LayoutParams(
        w, h, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        if (focusable) 0 else WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
        PixelFormat.TRANSLUCENT,
    )

    private fun notification(): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.overlay_channel),
            NotificationManager.IMPORTANCE_MIN))
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val openApp = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), flags)
        val stop = PendingIntent.getService(this, 1, Intent(this, OverlayService::class.java).setAction(ACTION_STOP), flags)
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.overlay_notification))
            .setContentIntent(openApp)
            .addAction(0, getString(R.string.overlay_stop), stop)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .build()
    }

    companion object {
        private const val CHANNEL = "overlay"
        private const val NOTIFICATION_ID = 1
        private const val ACTION_STOP = "org.reelcheck.STOP_OVERLAY"
        private const val BRAND = 0xFF1F4FD8.toInt()
        private val INSTAGRAM = setOf("com.instagram.android", "com.instagram.lite")

        @Volatile
        var running = false
            private set

        fun start(context: Context) {
            if (Permissions.canOverlay(context)) {
                ContextCompat.startForegroundService(context, Intent(context, OverlayService::class.java))
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, OverlayService::class.java))
        }
    }
}
