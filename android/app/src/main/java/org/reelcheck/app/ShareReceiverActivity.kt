package org.reelcheck.app

import android.app.Activity
import android.content.ClipData
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.core.content.IntentCompat

/**
 * Target of Instagram's Share sheet. A shared link or video is handed to [MainActivity], which runs the check.
 * Holds no state itself (noHistory).
 */
class ShareReceiverActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val forward = Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
        if (intent?.action == Intent.ACTION_SEND) {
            val video = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java)
            if (video != null && intent.type?.startsWith("video/") == true) {
                // The read grant travels with clipData, not with an extra.
                forward.putExtra(MainActivity.EXTRA_VIDEO, video).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                forward.clipData = ClipData.newRawUri("video", video)
            } else {
                forward.putExtra(MainActivity.EXTRA_LINK, intent.getStringExtra(Intent.EXTRA_TEXT))
            }
        }
        startActivity(forward)
        finish()
    }
}
