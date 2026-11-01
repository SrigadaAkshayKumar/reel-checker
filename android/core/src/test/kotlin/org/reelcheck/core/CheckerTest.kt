package org.reelcheck.core

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

/** The check flow against a fake backend that answers like backend/app/api/mobile.py. */
class CheckerTest {
    private val server = MockWebServer()
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    private var handler: (RecordedRequest) -> MockResponse = { MockResponse().setResponseCode(404) }
    private val store = object : TokenStore {
        override var token: String? = null
        override var userId: String? = null
    }
    private lateinit var checker: Checker

    @Before
    fun setUp() {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = handler(request.also { requests += it })
        }
        server.start()
        checker = Checker(ReelApi(server.url("/").toString()), store, pollMillis = 1)
    }

    @After
    fun tearDown() = server.shutdown()

    private fun json(body: String, code: Int = 200) =
        MockResponse().setResponseCode(code).setHeader("Content-Type", "application/json").setBody(body)

    private val session = """{"user_id":"u1","token":"tok-1","free_left":1,"ad_credits":0,"can_check":true}"""
    private val report = """{"report_id":"abc123abc123","verdict":"LIKELY_OLD_FOOTAGE","verdict_label":"Likely old footage",
        "confidence":0.82,"summary":"Seen in 2015.","evidence":[{"source":"youtube","title":"Old clip",
        "url":"https://youtu.be/x","date":"2015-03-02","similarity":0.97,"supports":"earlier_footage"}],
        "share_url":"https://reelcheck.example/r/abc123abc123","extra_field":{"ignored":true}}"""

    private fun job(status: String, step: String? = null, extra: String = "") =
        """{"job_id":"abc123abc123","status":"$status","step":${step?.let { "\"$it\"" } ?: "null"},
        "steps":["downloading","extracting","done"],"report_url":"/api/reports/abc123abc123"$extra}"""

    @Test
    fun `link check signs in, polls, and returns the report`() = runTest {
        var polls = 0
        handler = { r ->
            when (r.path) {
                "/api/app/session" -> json(session, 201)
                "/api/app/check" -> json(job("queued", extra = ""","charged":"free""""), 202)
                "/api/jobs/abc123abc123" -> json(if (++polls < 3) job("running", "downloading") else job("done", "done"))
                "/api/reports/abc123abc123" -> json(report)
                else -> MockResponse().setResponseCode(404)
            }
        }
        val seen = mutableListOf<String?>()
        val out = checker.run(CheckInput.Link("https://www.instagram.com/reel/C0deAbc123/")) { seen += it.step }
        assertTrue(out is Outcome.Done)
        assertEquals("LIKELY_OLD_FOOTAGE", (out as Outcome.Done).report.verdict)
        assertEquals("tok-1", store.token)
        assertTrue("downloading" in seen)
        val check = requests.first { it.path == "/api/app/check" }
        assertEquals("Bearer tok-1", check.getHeader("Authorization"))
        assertTrue(check.body.readUtf8().contains("https://www.instagram.com/reel/C0deAbc123/"))
    }

    @Test
    fun `no allowance asks for an ad`() = runTest {
        store.token = "tok-1"
        handler = {
            json("""{"detail":{"code":"watch_ad","message":"You've used today's free check.","ads_enabled":true}}""", 402)
        }
        val out = checker.run(CheckInput.Link("https://www.instagram.com/reel/C0deAbc123/"))
        assertEquals(Outcome.NeedAd("You've used today's free check.", adsEnabled = true), out)
    }

    @Test
    fun `a link the server could not fetch asks for the file`() = runTest {
        store.token = "tok-1"
        handler = { r ->
            when (r.path) {
                "/api/app/check" -> json(job("queued"), 202)
                else -> json(job("failed", "failed", ""","error":"Share the file instead.","error_code":"need_file""""))
            }
        }
        assertEquals(Outcome.NeedFile("Share the file instead."),
            checker.run(CheckInput.Link("https://www.instagram.com/reel/C0deAbc123/")))
    }

    @Test
    fun `a lost account signs in again once`() = runTest {
        store.token = "old"
        handler = { r ->
            when {
                r.path == "/api/app/session" -> json(session, 201)
                r.getHeader("Authorization") == "Bearer old" ->
                    json("""{"detail":{"code":"signed_out","message":"Please reopen the app."}}""", 401)
                else -> json("""{"user_id":"u1","free_left":1,"ad_credits":2,"can_check":true}""")
            }
        }
        assertEquals(2, checker.allowance().ad_credits)
        assertEquals("tok-1", store.token)
    }

    @Test
    fun `file upload is multipart with its name`() = runTest {
        store.token = "tok-1"
        handler = { r -> if (r.path == "/api/app/check") json(job("done", "done", ""","cached":true""")) else json(report) }
        val file = File.createTempFile("reel", ".mp4").apply { writeBytes(byteArrayOf(1, 2, 3)); deleteOnExit() }
        val out = checker.run(CheckInput.Video(VideoFile(file, "reel.mp4")))
        assertTrue(out is Outcome.Done && out.cached)
        val body = requests.first { it.path == "/api/app/check" }.body.readUtf8()
        assertTrue(body.contains("filename=\"reel.mp4\""))
    }

    @Test
    fun `server and network errors become user messages`() = runTest {
        store.token = "tok-1"
        handler = { MockResponse().setResponseCode(502).setBody("<html>Bad gateway</html>") }
        val out = checker.run(CheckInput.Link("https://www.instagram.com/reel/C0deAbc123/"))
        assertEquals(Outcome.Failed("The server had a problem. Please try again in a minute."), out)
        server.shutdown()
        val offline = checker.run(CheckInput.Link("https://www.instagram.com/reel/C0deAbc123/"))
        assertTrue((offline as Outcome.Failed).message.startsWith("Can't reach the server"))
    }

    @Test
    fun `waiting for an ad credit stops when it arrives`() = runTest {
        store.token = "tok-1"
        var calls = 0
        handler = { json("""{"user_id":"u1","ad_credits":${if (++calls < 2) 0 else 1}}""") }
        assertTrue(checker.waitForCredit(before = 0, waitMillis = 1))
        assertEquals(2, calls)
        handler = { json("""{"user_id":"u1","ad_credits":0}""") }
        assertFalse(checker.waitForCredit(before = 0, tries = 2, waitMillis = 1))
    }
}
