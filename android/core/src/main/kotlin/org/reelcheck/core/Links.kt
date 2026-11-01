package org.reelcheck.core

/**
 * Finds an Instagram reel link in text the user shared or copied ("Check out this reel https://…").
 * Same accepted forms as the backend (backend/app/pipeline/fetch.py); the server re-checks anyway.
 */
object Links {
    private val LINK = Regex(
        """https?://(?:www\.|m\.)?instagram\.com/(?:[A-Za-z0-9_.]{1,30}/)?(reels?|p|tv)/([A-Za-z0-9_-]{5,40})/?(?:\?[^\s]*)?""",
    )

    fun findReel(text: String?): String? = text?.let { LINK.find(it)?.value }

    fun isReel(text: String?): Boolean = findReel(text) != null
}
