package org.reelcheck.app

import android.app.Application
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.IntentCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import org.reelcheck.core.CheckInput
import org.reelcheck.core.Links
import org.reelcheck.core.Report
import org.reelcheck.core.Tone
import org.reelcheck.core.Wording

class MainViewModel(app: Application) : AndroidViewModel(app) {
    val checks = CheckController(app, viewModelScope)

    fun checkVideo(context: Context, uri: Uri) {
        viewModelScope.launch {
            try {
                checks.check(CheckInput.Video(Videos.copy(context, uri)))
            } catch (e: java.io.IOException) {
                checks.reset()
                failed = e.message ?: "Can't read this video."
            }
        }
    }

    var failed by mutableStateOf<String?>(null)
}

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) handle(intent)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF1F4FD8))) {
                Surface(Modifier.fillMaxSize()) { MainScreen(vm) }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    /** A link or video handed over by [ShareReceiverActivity] or the floating button. */
    private fun handle(intent: Intent?) {
        intent ?: return
        Links.findReel(intent.getStringExtra(EXTRA_LINK))?.let { vm.checks.check(CheckInput.Link(it)) }
        IntentCompat.getParcelableExtra(intent, EXTRA_VIDEO, Uri::class.java)?.let { vm.checkVideo(this, it) }
        if (intent.getBooleanExtra(EXTRA_PICK_FILE, false)) vm.failed = PICK_HINT
    }

    companion object {
        const val EXTRA_LINK = "org.reelcheck.LINK"
        const val EXTRA_VIDEO = "org.reelcheck.VIDEO"
        const val EXTRA_PICK_FILE = "org.reelcheck.PICK_FILE"
        const val PICK_HINT = "Save the reel to your phone (or screen-record it), then choose the video here."
    }
}

@Composable
private fun MainScreen(vm: MainViewModel) {
    val context = LocalContext.current
    val state by vm.checks.state.collectAsState()
    val allowance by vm.checks.allowance.collectAsState()
    var link by rememberSaveable { mutableStateOf("") }
    val pickVideo = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            vm.failed = null
            vm.checkVideo(context, uri)
        }
    }

    // Refresh the allowance and the overlay permission state whenever the screen comes back.
    var resumed by remember { mutableStateOf(0) }
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val observer = LifecycleEventObserver { _, e ->
            if (e == Lifecycle.Event.ON_RESUME) {
                resumed++
                vm.checks.refreshAllowance()
            }
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }

    Column(
        Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Reel Check", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        Text("Is this reel old footage shared as new? Paste its link or share the video.",
            style = MaterialTheme.typography.bodyMedium)
        allowance?.let { Text(Wording.allowance(it), style = MaterialTheme.typography.labelLarge) }

        OutlinedTextField(
            value = link, onValueChange = { link = it }, label = { Text("Instagram reel link") },
            singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = {
                val clip = (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).primaryClip
                clip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.let { link = it.toString() }
            }) { Text("Paste") }
            Button(enabled = Links.isReel(link) && state !is CheckState.Working, onClick = {
                vm.failed = null
                vm.checks.check(CheckInput.Link(Links.findReel(link)!!))
            }) { Text("Check link") }
        }
        TextButton(onClick = { pickVideo.launch("video/*") }) { Text("Or choose a video file") }

        vm.failed?.let { Notice(it) }
        CheckStateView(state, vm.checks, onPickFile = { pickVideo.launch("video/*") })

        Spacer(Modifier.height(8.dp))
        FloatingButtonSettings(resumed)
        TextButton(onClick = { openUrl(context, BuildConfig.SITE_URL.trimEnd('/') + "/privacy") }) {
            Text("Privacy & terms")
        }
    }
}

@Composable
private fun CheckStateView(state: CheckState, checks: CheckController, onPickFile: () -> Unit) {
    when (state) {
        CheckState.Idle -> Unit
        is CheckState.Working -> Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.padding(end = 12.dp))
            Text(state.text)
        }
        is CheckState.Done -> ReportCard(state.report, state.cached, checks)
        is CheckState.NeedAd -> Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(state.message)
                state.note?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                if (state.canWatch) Button(onClick = { checks.watchAdAndRetry() }) {
                    Text("Watch a short ad to run another check")
                }
            }
        }
        is CheckState.NeedFile -> Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(state.message)
                Button(onClick = onPickFile) { Text("Choose the video file") }
            }
        }
        is CheckState.Error -> Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(state.message)
                OutlinedButton(onClick = { checks.retry() }) { Text("Try again") }
            }
        }
    }
}

fun openUrl(context: Context, url: String) {
    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } // no browser: nothing to do
}

fun toneColor(tone: Tone) = when (tone) {
    Tone.BAD -> Color(0xFFB42318)
    Tone.WARN -> Color(0xFFB54708)
    Tone.INFO -> Color(0xFF175CD3)
    Tone.MUTED -> Color(0xFF475467)
}

@Composable
private fun ReportCard(report: Report, cached: Boolean, checks: CheckController) {
    val context = LocalContext.current
    val v = Wording.verdict(report.verdict)
    var thanked by remember(report.report_id) { mutableStateOf(false) }
    fun open(url: String) = openUrl(context, url)

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(v.label, color = toneColor(v.tone), style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold)
            Text(v.meaning, style = MaterialTheme.typography.bodySmall)
            Text(Wording.confidence(report.confidence), style = MaterialTheme.typography.labelLarge)
            if (report.summary.isNotBlank()) Text(report.summary)
            if (report.summary_local.isNotBlank()) Text(report.summary_local)
            report.evidence.take(5).forEach { e ->
                val bits = listOfNotNull(Wording.source(e.source), Wording.date(e.date).ifBlank { null },
                    Wording.similarity(e.similarity), e.rating)
                Column(Modifier.fillMaxWidth()) {
                    Text(e.title.ifBlank { "Source" }, fontWeight = FontWeight.SemiBold)
                    Text(bits.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                    e.url?.takeIf { it.startsWith("http") }?.let { url ->
                        TextButton(onClick = { open(url) }) { Text("Open source") }
                    }
                }
            }
            if (report.partial) Text("Some searches could not run, so this result may be incomplete.",
                style = MaterialTheme.typography.bodySmall)
            if (cached) Text("Checked before: this is the earlier result.", style = MaterialTheme.typography.bodySmall)
            Text(Wording.DISCLAIMER, style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (report.share_url.isNotBlank()) {
                    Button(onClick = { open(report.share_url) }) { Text("Full report") }
                    OutlinedButton(onClick = {
                        val send = Intent(Intent.ACTION_SEND).setType("text/plain")
                            .putExtra(Intent.EXTRA_TEXT, "${v.label}: ${report.share_url}")
                        context.startActivity(Intent.createChooser(send, "Share report"))
                    }) { Text("Share") }
                }
            }
            if (thanked) {
                Text("Thanks, we'll review it.", style = MaterialTheme.typography.bodySmall)
            } else {
                TextButton(onClick = { checks.feedback(report, correct = false); thanked = true }) {
                    Text("This verdict looks wrong")
                }
            }
            TextButton(onClick = { checks.reset() }) { Text("Check another reel") }
        }
    }
}

@Composable
private fun Notice(text: String) = Card(Modifier.fillMaxWidth()) { Text(text, Modifier.padding(16.dp)) }

/** Turning on the floating button, with a plain explanation of each permission before opening its settings. */
@Composable
private fun FloatingButtonSettings(resumed: Int) {
    val context = LocalContext.current
    val prefs = context.reel.prefs
    // Re-read on every resume: the user may have just granted something in Settings.
    val overlay = remember(resumed) { Permissions.canOverlay(context) }
    val usage = remember(resumed) { Permissions.hasUsageAccess(context) }
    var running by remember(resumed) { mutableStateOf(OverlayService.running) }
    var always by remember { mutableStateOf(prefs.alwaysShowDot) }
    val notify = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        OverlayService.start(context)
        running = true
    }

    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Floating check button", Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                Switch(checked = running, enabled = overlay, onCheckedChange = { on ->
                    if (on) {
                        if (Build.VERSION.SDK_INT >= 33) notify.launch(android.Manifest.permission.POST_NOTIFICATIONS)
                        else { OverlayService.start(context); running = true }
                    } else {
                        OverlayService.stop(context)
                        running = false
                    }
                })
            }
            Text("A small button over Instagram: tap it, paste the reel link, see the result without leaving the app.",
                style = MaterialTheme.typography.bodySmall)
            if (!overlay) {
                Text("Step 1: allow \"Display over other apps\", so the button can appear on top of Instagram. " +
                    "It only shows the button and the result card; it can't see or read your screen.",
                    style = MaterialTheme.typography.bodySmall)
                OutlinedButton(onClick = { context.startActivity(Permissions.overlaySettings(context)) }) {
                    Text("Allow display over other apps")
                }
            }
            if (!usage && !always) {
                Text("Optional: allow \"Usage access\" so the button shows only while Instagram is open. " +
                    "The app only checks which app is on screen; it doesn't read what you do in it.",
                    style = MaterialTheme.typography.bodySmall)
                OutlinedButton(onClick = { context.startActivity(Permissions.usageSettings()) }) {
                    Text("Allow usage access")
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Show the button over every app", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                Switch(checked = always, onCheckedChange = { always = it; prefs.alwaysShowDot = it })
            }
        }
    }
}
