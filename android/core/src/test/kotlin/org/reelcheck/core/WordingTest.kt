package org.reelcheck.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WordingTest {
    @Test
    fun `finds reel links in shared text`() {
        assertEquals("https://www.instagram.com/reel/C0deAbc123/?igsh=MWQ1",
            Links.findReel("Watch this reel https://www.instagram.com/reel/C0deAbc123/?igsh=MWQ1 now"))
        assertEquals("https://instagram.com/reels/C0deAbc123", Links.findReel("https://instagram.com/reels/C0deAbc123"))
        assertEquals("https://m.instagram.com/p/C0deAbc123/", Links.findReel("https://m.instagram.com/p/C0deAbc123/"))
        assertNull(Links.findReel("https://www.instagram.com/someuser/"))
        assertNull(Links.findReel("https://instagram.com.evil.example/reel/C0deAbc123/"))
        assertNull(Links.findReel("https://example.com/video.mp4"))
        assertNull(Links.findReel(null))
    }

    @Test
    fun `verdict wording never says real or fake`() {
        for ((_, v) in Wording.VERDICTS) {
            assertFalse(v.label.contains("real", ignoreCase = true))
            assertFalse(v.label.contains("fake", ignoreCase = true))
        }
        assertEquals("Unverified", Wording.verdict("SOMETHING_NEW").label) // unknown codes fall back safely
        assertEquals(Tone.INFO, Wording.verdict("NO_CONTRADICTION_FOUND").tone)
    }

    @Test
    fun `numbers and dates`() {
        assertEquals("97% frame match", Wording.similarity(0.97))
        assertEquals("frames do not match", Wording.similarity(0.72))
        assertNull(Wording.similarity(null))
        assertEquals("Confidence 82%", Wording.confidence(0.82))
        assertEquals("2 Mar 2015", Wording.date("2015-03-02"))
        assertEquals("1 Nov 2026", Wording.date("2026-11-01T10:33:04+00:00"))
        assertEquals("sometime", Wording.date("sometime"))
    }

    @Test
    fun `progress and allowance`() {
        assertEquals("Waiting in line (2 ahead)", Wording.step(Progress(null, 3, emptyList())))
        assertEquals("Fetching the reel", Wording.step(Progress("downloading", null, emptyList())))
        assertEquals("1 check free today", Wording.allowance(Allowance(free_left = 1)))
        assertEquals("2 earned checks", Wording.allowance(Allowance(ad_credits = 2)))
        assertTrue(Wording.allowance(Allowance(resets_at = "2026-11-01T18:30:00+00:00"))
            .startsWith("Today's free check is used. Next one at "))
    }
}
