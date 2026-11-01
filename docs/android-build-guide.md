# Reel Fact-Checker: Zero-Cost End-to-End Build Guide

Android app with a floating dot over Instagram. Paste a reel link, get a verdict on whether the footage is old or misleading. Free first check every day; every further check needs one rewarded video ad.

Written 29 Oct 2026. Free-tier limits change often, so re-check each service's page before you depend on a number.

---

## 0. The honest zero-cost picture

Almost everything can be free. Three things you should know up front:

| Item | Cost | Notes |
|---|---|---|
| Google Play developer account | **$25 one time** | Only needed to publish. You can build and test with a side-loaded APK for $0. |
| Play testing rule | Time, not money | New personal accounts need **12 testers opted in for 14 continuous days** before production access. Start this early (Phase 5). |
| Everything else | $0 | Android Studio, AdMob, Supabase, Gemini free tier, Fact Check API, Render free tier, GitHub Pages. |

What will break first at zero cost, in order:

1. **SerpApi free plan: 250 searches per month.** That is the footage-age check. At 1 to 3 searches per check, you get roughly 80 to 250 checks a month. Fine for beta, not for real traffic.
2. **Gemini free tier daily request cap.** Published figures vary by source (roughly 500 to 1,500 requests a day for Flash models, not guaranteed, and Google cut free limits in late 2025). Your real number is in Google AI Studio.
3. **Render free web service sleeps after 15 minutes idle** and takes about a minute to wake.

Economics warning (my estimate, verify with real AdMob data): a rewarded ad view in India probably pays far less than one paid reverse-image-search call costs. So when you outgrow the free plan, do not just buy more searches. Use the free checks first and call the paid search only when they are inconclusive.

---

## 1. Product rules (the monetization model)

| Situation | What happens |
|---|---|
| First check of the day | Free, no ad. Resets at midnight India time. |
| Second and later checks | User taps **Watch ad to check**, watches one rewarded video, then the check runs. |
| User has no time | Phase 2 only: pay to skip. A one-time Play Billing pack, such as 10 checks. Do not build this in the MVP. |

Rules to keep AdMob and Play happy:

- The ad must be **opt-in with a clear button** ("Watch a short ad to run another check"). Never force it or hide it.
- Never click your own live ads. Use test ad unit IDs during development or Google can suspend your account.
- The server, not the app, counts free checks and ad credits. A client-only counter is trivial to cheat.

---

## 2. Architecture

```
Instagram (user)
   |  Share sheet link, or paste
   v
Android app (Kotlin)
 - Floating dot service (overlay)
 - Paste card -> 75% result card
 - Transparent AdActivity (shows rewarded ad)
   |  HTTPS + Supabase anonymous login token
   v
FastAPI backend on Render (free)
 1. spend_check(user)   -> free | ad | denied   (Supabase Postgres)
 2. download video      -> yt-dlp, else ask user for the file
 3. ffmpeg key frames
 4. Gemini (free tier)  -> describe video, extract claim
 5. Fact Check Tools API (free) -> existing fact-checks
 6. SerpApi Google Lens (250/mo free) -> earliest matches   [only if needed]
 7. Gemini              -> JSON verdict
   ^
   |  AdMob server-side verification (SSV) callback -> grants an ad credit
AdMob
```

---

## 3. Free tool stack

| Need | Tool | Free limit (as found Oct 2026) |
|---|---|---|
| IDE | Android Studio | Free |
| App language | Kotlin, XML views for the overlay, Jetpack Compose for normal screens | Free |
| Ads | AdMob rewarded ads | Free to join. Real ads need a published or testing app. Test ID below. |
| Backend host | Render free web service | 750 instance hours a month, sleeps after 15 min idle, about 1 min wake, files wiped on restart |
| Database, login, temp image storage | Supabase free project | Check current limits; free projects can pause when idle (verify) |
| LLM and video understanding | Gemini API via Google AI Studio | Free tier, limits per project, shown in AI Studio. **Free-tier prompts may be used by Google for training.** Mention this in your privacy policy. |
| Existing fact-checks | Google Fact Check Tools API | Free with an API key. Has `claims:search` and `claims:imageSearch`. |
| Reverse image search | SerpApi `google_lens` engine | 250 searches a month free. Needs a **public image URL**, not an upload. |
| Download reel | `yt-dlp` | Free, but see the risk note in Phase 1 |
| Frames | `ffmpeg` | Free |
| Privacy policy page | GitHub Pages | Free |
| Crash and testing | Firebase Crashlytics (optional) | Free |

Rewarded test ad unit ID (Google's published test ID): `ca-app-pub-3940256099942544/5224354917`

---

## 4. How to use AI tools to build this

Use any chat AI you like (Claude, Gemini, ChatGPT free tiers) plus the AI assistant inside Android Studio if you have it. Rules that save hours:

1. **One phase per chat.** Paste the phase prompt from Section 10, then the error logs as you hit them.
2. **Always paste the exact error and the file**, not a description.
3. **Ask for small, runnable steps** ("make the dot appear and drag, nothing else").
4. **Verify permissions and policies yourself** in official docs. AI tools are weakest on fast-changing Play and AdMob rules.
5. **Commit to GitHub after every working step** so you can roll back when an AI edit breaks things.

---

## 5. Phase 0: Accounts and keys (Day 1)

| Account | Where | You get |
|---|---|---|
| Google account for everything | google.com | One login for the rest |
| Google AI Studio | aistudio.google.com | `GEMINI_API_KEY` |
| Google Cloud project, enable **Fact Check Tools API** | console.cloud.google.com | `FACTCHECK_API_KEY` |
| SerpApi | serpapi.com | `SERPAPI_API_KEY` (250 a month free, no card) |
| Supabase | supabase.com | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, anon key |
| AdMob | admob.google.com | App ID and rewarded ad unit ID |
| Render | render.com | Hosting |
| GitHub | github.com | Code, Pages for privacy policy |
| Play Console | play.google.com/console | $25, do this when the first build is ready |

Never put the service keys in the Android app. They live only in Render environment variables.

---

## 6. Phase 1: Backend (Days 2 to 6)

**Build and test this before any Android work.** It decides whether the whole product works.

### 6.1 Supabase setup (SQL editor)

```sql
create table usage (
  user_id uuid not null,
  day date not null,
  free_used boolean not null default false,
  ad_credits int not null default 0,
  primary key (user_id, day)
);

create table ssv_seen (transaction_id text primary key);

create or replace function spend_check(uid uuid) returns text
language plpgsql as $$
declare d date := (now() at time zone 'Asia/Kolkata')::date;
declare r usage%rowtype;
begin
  insert into usage(user_id, day) values (uid, d) on conflict do nothing;
  select * into r from usage where user_id = uid and day = d for update;
  if not r.free_used then
    update usage set free_used = true where user_id = uid and day = d;
    return 'free';
  elsif r.ad_credits > 0 then
    update usage set ad_credits = ad_credits - 1 where user_id = uid and day = d;
    return 'ad';
  end if;
  return 'denied';
end $$;

create or replace function grant_ad_credit(uid uuid) returns void
language plpgsql as $$
declare d date := (now() at time zone 'Asia/Kolkata')::date;
begin
  insert into usage(user_id, day, ad_credits) values (uid, d, 1)
  on conflict (user_id, day) do update set ad_credits = usage.ad_credits + 1;
end $$;
```

Also add a `refund_check(uid, kind)` function that gives the free check or credit back if the analysis fails. Ask your AI tool to write it.

Enable **Anonymous sign-ins** in Supabase Auth. The app signs in silently, so users never create an account.

Create a public storage bucket named `frames` for temporary frame images (needed because Google Lens takes a URL).

### 6.2 FastAPI skeleton (`main.py`)

This is a skeleton. Have your AI tool finish it and test every function.

```python
import os, json, subprocess, tempfile, time, uuid, glob
import httpx
from fastapi import FastAPI, Header, HTTPException, UploadFile, Form
from google import genai
from google.genai import types

app = FastAPI()
gem = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
SB = os.environ["SUPABASE_URL"]
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
SB_H = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}

@app.get("/health")
def health():
    return {"ok": True}          # app calls this on launch to wake Render

def user_from_token(authorization: str) -> str:
    r = httpx.get(f"{SB}/auth/v1/user",
                  headers={"apikey": SB_KEY, "Authorization": authorization})
    if r.status_code != 200:
        raise HTTPException(401, "bad token")
    return r.json()["id"]

def rpc(name: str, body: dict):
    r = httpx.post(f"{SB}/rest/v1/rpc/{name}", headers=SB_H, json=body)
    r.raise_for_status()
    return r.json()

@app.post("/check")
async def check(authorization: str = Header(...),
                url: str = Form(None), video: UploadFile = None):
    uid = user_from_token(authorization)
    kind = rpc("spend_check", {"uid": uid})
    if kind == "denied":
        raise HTTPException(402, "watch_ad")        # app shows the ad button
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = await get_video(tmp, url, video)
            if path is None:
                rpc("refund_check", {"uid": uid, "kind": kind})
                return {"status": "need_file"}      # ask user to share the video file
            return {"status": "ok", **analyze(tmp, path, url)}
    except Exception:
        rpc("refund_check", {"uid": uid, "kind": kind})
        raise

async def get_video(tmp, url, video):
    if video is not None:
        p = os.path.join(tmp, "in.mp4")
        open(p, "wb").write(await video.read())
        return p
    out = os.path.join(tmp, "in.mp4")
    res = subprocess.run(["yt-dlp", "-f", "mp4", "-o", out, url],
                         capture_output=True, timeout=90)
    return out if res.returncode == 0 and os.path.exists(out) else None

def analyze(tmp, path, url):
    # 1. Understand the video
    f = gem.files.upload(file=path)
    while gem.files.get(name=f.name).state.name == "PROCESSING":
        time.sleep(2)
    desc = json.loads(gem.models.generate_content(
        model="gemini-2.5-flash",
        contents=[f, "Describe the footage: event type, place clues, visible text, "
                     "language, signs of old or stock footage. Then give the claim a "
                     "caption would make and 3 search queries. Reply as JSON with keys "
                     "description, claim, queries."],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    ).text)

    # 2. Existing fact-checks (free)
    checks = []
    for q in desc["queries"][:3]:
        r = httpx.get("https://factchecktools.googleapis.com/v1alpha1/claims:search",
                      params={"query": q, "key": os.environ["FACTCHECK_API_KEY"]})
        for c in r.json().get("claims", [])[:3]:
            for rv in c.get("claimReview", [])[:1]:
                checks.append({"claim": c.get("text"), "rating": rv.get("textualRating"),
                               "publisher": rv.get("publisher", {}).get("name"),
                               "url": rv.get("url"), "date": rv.get("reviewDate")})

    # 3. Reverse image search, only if no fact-check was found (saves the 250/month)
    matches = []
    if not checks:
        matches = lens_matches(tmp, path)

    # 4. Verdict
    verdict = json.loads(gem.models.generate_content(
        model="gemini-2.5-flash",
        contents=["You are a careful fact-checker. Use ONLY this evidence. If evidence "
                  "is weak, say Unverified. Reply as JSON with keys verdict (one of: "
                  "Likely Old Footage, Misleading Context, Unverified, Likely Authentic), "
                  "confidence (low, medium, high), earliest_date (or null), explanation "
                  "(2 sentences, simple English), sources (list of urls).\n\n"
                  + json.dumps({"video": desc, "fact_checks": checks, "matches": matches})],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    ).text)
    return verdict

def lens_matches(tmp, path):
    frame = os.path.join(tmp, "f.jpg")
    subprocess.run(["ffmpeg", "-y", "-i", path, "-vf", "select=eq(n\\,30)",
                    "-frames:v", "1", frame], capture_output=True)
    if not os.path.exists(frame):
        return []
    name = f"{uuid.uuid4()}.jpg"
    httpx.post(f"{SB}/storage/v1/object/frames/{name}",
               headers={**SB_H, "Content-Type": "image/jpeg"}, content=open(frame, "rb").read())
    public = f"{SB}/storage/v1/object/public/frames/{name}"
    try:
        r = httpx.get("https://serpapi.com/search.json",
                      params={"engine": "google_lens", "url": public,
                              "api_key": os.environ["SERPAPI_API_KEY"]}, timeout=60)
        return [{"title": m.get("title"), "link": m.get("link"), "source": m.get("source")}
                for m in r.json().get("visual_matches", [])[:8]]
    finally:
        httpx.delete(f"{SB}/storage/v1/object/frames/{name}", headers=SB_H)
```

### 6.3 AdMob SSV endpoint (so ad credits cannot be faked)

AdMob calls your URL with a **GET** after a completed ad. The call carries `user_id`, `transaction_id`, `signature` and `key_id`. Your endpoint must:

1. Verify the signature using Google's published AdMob verifying keys (see the AdMob SSV doc).
2. Reject a `transaction_id` already in `ssv_seen`.
3. Call `grant_ad_credit(user_id)`.

Ask your AI tool: "Implement an AdMob rewarded-ad SSV GET callback in FastAPI that verifies the ECDSA signature, dedupes on transaction_id using Supabase, and calls the grant_ad_credit RPC. Follow Google's official SSV documentation."

In AdMob: ad unit, Advanced settings, set up server-side verification, callback URL `https://<your-app>.onrender.com/admob/ssv`.

### 6.4 Deploy on Render

1. Put `main.py`, `requirements.txt` (`fastapi uvicorn httpx python-multipart google-genai yt-dlp`) and a `Dockerfile` that also installs `ffmpeg` on GitHub.
2. Render: New Web Service, connect the repo, free instance.
3. Add the environment variables from Phase 0.
4. Test with Postman or curl: `/health`, then `/check` with a real reel link and with a video file.

### 6.5 The big risk: getting the video

- Instagram has no official download API. `yt-dlp` often fails on Instagram, especially from data-center IPs like Render's. Downloading may also break Instagram's terms.
- **Test this on day 2.** If it fails from Render, make the **video-file path the primary one**: the user downloads or screen-records the reel, then shares the file to your app. The link-paste flow becomes a convenience that sometimes works.
- Do not store videos. Delete after analysis (the temp directory above does this).

### 6.6 Build a test set before moving on

Collect 20 reels or videos with known answers: 10 that fact-checkers (Alt News, BOOM, PIB Fact Check) have already debunked as old footage, and 10 genuine recent ones. Run all 20. Count wrong "Old Footage" verdicts separately from missed fakes. **A false accusation on real news is the worst failure**, so tune the prompt until "Unverified" is the default when evidence is thin.

---

## 7. Phase 2: Basic Android app (Days 7 to 11)

Goal: a normal app screen that signs in, pastes a link, calls `/check`, and shows the verdict. No overlay yet.

1. New Android Studio project, Kotlin, Jetpack Compose, min SDK 26.
2. Add Supabase anonymous sign-in (REST is fine) and store the access token.
3. On launch, call `/health` to wake Render.
4. Screen: text field, Paste button, Check button, loading state, result card.
5. Result card: verdict badge, confidence, earliest date, sources as tappable links, 2-sentence explanation.
6. Handle `402 watch_ad` (show the ad button) and `need_file` (open a file picker, then re-send as multipart).
7. Add a share-target so Instagram's Share sheet can send a link:

```xml
<activity android:name=".ShareReceiverActivity" android:exported="true"
          android:theme="@style/Theme.Translucent">
  <intent-filter>
    <action android:name="android.intent.action.SEND"/>
    <category android:name="android.intent.category.DEFAULT"/>
    <data android:mimeType="text/plain"/>
  </intent-filter>
  <intent-filter>
    <action android:name="android.intent.action.SEND"/>
    <category android:name="android.intent.category.DEFAULT"/>
    <data android:mimeType="video/*"/>
  </intent-filter>
</activity>
```

Side-load the APK on your phone and test end to end here.

---

## 8. Phase 3: The floating dot (Days 12 to 18)

### 8.1 Permissions and manifest

```xml
<uses-permission android:name="android.permission.INTERNET"/>
<uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>
<uses-permission android:name="android.permission.PACKAGE_USAGE_STATS"
                 tools:ignore="ProtectedPermissions"/>

<service android:name=".OverlayService" android:exported="false"
         android:foregroundServiceType="specialUse">
  <property android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
            android:value="Shows a floating reel-check button over Instagram"/>
</service>
```

Android 14 and later need a declared foreground-service type. Confirm the right type and Play declaration in current Android docs.

First-run screen sends the user to two settings pages:

- `Settings.ACTION_MANAGE_OVERLAY_PERMISSION` (Display over other apps)
- `Settings.ACTION_USAGE_ACCESS_SETTINGS` (Usage access, for detecting Instagram)

Explain in plain words why each is needed before opening the settings page.

### 8.2 Overlay states

One service, three states, all inside a `WindowManager` view with `TYPE_APPLICATION_OVERLAY`:

| State | View | Window flags |
|---|---|---|
| Dot | 48dp draggable circle | `FLAG_NOT_FOCUSABLE` |
| Input card | Small card: text field, Paste, Check | Focusable (remove `FLAG_NOT_FOCUSABLE`) so the keyboard and clipboard work |
| Result card | 75% of screen height, X in the corner | Focusable |

The X sets state back to Dot. It never stops the service.

Use classic Android Views for the overlay. Compose inside a service overlay needs extra lifecycle setup and is a common time sink. If you prefer Compose, tell your AI tool to wire a `LifecycleOwner` and `SavedStateRegistryOwner` for the `ComposeView`.

Drag skeleton:

```kotlin
dot.setOnTouchListener(object : View.OnTouchListener {
    var startX = 0; var startY = 0; var touchX = 0f; var touchY = 0f; var moved = false
    override fun onTouch(v: View, e: MotionEvent): Boolean {
        when (e.action) {
            MotionEvent.ACTION_DOWN -> { startX = lp.x; startY = lp.y
                touchX = e.rawX; touchY = e.rawY; moved = false }
            MotionEvent.ACTION_MOVE -> {
                lp.x = startX + (e.rawX - touchX).toInt()
                lp.y = startY + (e.rawY - touchY).toInt()
                if (abs(e.rawX - touchX) > 10 || abs(e.rawY - touchY) > 10) moved = true
                wm.updateViewLayout(dot, lp) }
            MotionEvent.ACTION_UP -> if (!moved) showInputCard()   // tap
        }
        return true
    }
})
```

### 8.3 Show the dot only when Instagram is open

Poll `UsageStatsManager.queryEvents` about once a second from the service, find the latest foreground event, and compare the package to `com.instagram.android`. Show the dot when it matches, hide it otherwise. Add a setting "Always show dot" as a fallback. Do not use an Accessibility Service for this; Google restricts it heavily.

### 8.4 Clipboard

On Android 10 and later, only the focused app or the default keyboard can read the clipboard. Make the input card focusable, then read `ClipboardManager.primaryClip` when the card gains focus and fill the field. Keep a manual Paste button as the fallback. Test on at least two phones.

---

## 9. Phase 4: Ads, limits and a clean flow (Days 19 to 23)

### 9.1 Rewarded ads need an Activity

An ad cannot be shown from the overlay service. It must be shown from an `Activity`. The flow:

1. User taps Check, backend replies `402 watch_ad`.
2. Overlay shows "Watch a short ad to run another check" with a button.
3. Button starts a **transparent `AdActivity`** from the service (`FLAG_ACTIVITY_NEW_TASK`). Apps holding the overlay permission are generally allowed to start activities from the background; test it on Android 12 to 15.
4. `AdActivity` loads the rewarded ad, sets the SSV user ID to the Supabase user id, shows it, then `finish()`es. The user lands back in Instagram.
5. On `onUserEarnedReward`, notify the service. The service waits a moment, retries `/check`, and shows the result card.

AdMob setup in code: use the user ID option in the ad's server-side verification options so AdMob forwards it to your SSV callback. Use the test unit ID until release, then swap in your real ID.

### 9.2 Edge cases to handle

| Case | Behavior |
|---|---|
| Ad fails to load | Message: "No ad right now, try again in a minute." Do not give a free check. |
| User closes the ad early | No reward, no check. |
| Reward received but credit not yet granted (SSV delay) | Retry `/check` 3 times, 2 seconds apart, before showing an error. |
| Backend asleep | Show "Waking up the server, up to a minute" on the first check. |
| Analysis fails | Backend refunds the free check or credit. |
| Video could not be fetched | Ask the user to share the video file. |

---

## 10. Copy-paste prompts for your AI tool

**Backend**
> I'm building a FastAPI backend on Render's free tier. Here is my main.py and my Supabase SQL (paste both). Fix bugs, add the refund_check SQL function, add an AdMob rewarded-ad server-side-verification GET endpoint that verifies the signature and dedupes on transaction_id, and write a Dockerfile that installs ffmpeg and yt-dlp. Keep everything within free tiers. Explain each change briefly.

**Android basic app**
> Create a Kotlin Android app (min SDK 26, Jetpack Compose). It signs in anonymously to Supabase via REST, stores the token, calls GET /health on launch, and has a screen with a link field, Paste button, Check button, and a result card showing verdict, confidence, earliest date, explanation and clickable source links. Call POST /check with the Authorization header. Handle HTTP 402 and a JSON status of "need_file". Give me full files, not snippets.

**Overlay**
> Add a foreground Service that shows a draggable 48dp floating dot with WindowManager TYPE_APPLICATION_OVERLAY using classic Views. Tapping the dot expands to a small card with an EditText, Paste button and Check button; make the window focusable only while the card is open. After a result arrives, resize the card to 75% of screen height with an X button that collapses back to the dot without stopping the service. Handle Android 13 to 15 notification and foreground-service-type requirements.

**Instagram detection**
> In my OverlayService, poll UsageStatsManager every second and show the dot only while com.instagram.android is the foreground app. Add a first-run screen that sends the user to the Overlay and Usage Access settings pages with a plain-language explanation for each, and re-checks the permissions when they return.

**Ads**
> Add AdMob rewarded ads using the current Google Mobile Ads SDK. Create a transparent AdActivity launched from my overlay service, load and show a rewarded ad with the test unit ID, set the SSV user ID to the Supabase user id, and report the result back to the service. Handle load failure, early close, and retry of /check after reward.

**Privacy policy**
> Write a plain-language privacy policy for an Android app that sends a user-provided social media link or video to a server for analysis using AI and fact-check services, stores an anonymous user ID and daily usage counts, shows AdMob ads, and does not store videos. Mention that AI providers may process the content. Output as a single HTML page for GitHub Pages.

---

## 11. Phase 5: Play Store setup (start early, in parallel)

The 14-day testing clock is the longest part of the whole project, so start it as soon as the Phase 2 build works. You can keep updating the build during the test.

1. Pay the $25 and complete identity verification.
2. Create the app. Upload a signed AAB to **Closed testing**.
3. Recruit **12 or more testers** (friends, classmates, your YouTube audience) to opt in and stay opted in for **14 continuous days**. Opted in, not just invited.
4. Fill in: privacy policy URL (GitHub Pages), Data safety form, ads declaration, content rating, target audience (adults).
5. Permission declarations. Expect Play to ask why you use the overlay permission and usage access. Core purpose answer: a floating reel-check button that shows only over Instagram. Check the current policy wording in Play Console; this is the step most likely to need a revision.
6. After 14 days, apply for production access.
7. In AdMob, link the app, switch from test IDs to your real ad unit ID (never test with live ads on your own phone).

Release to **India only** at first. It limits support load and policy surface.

---

## 12. Quality and trust checklist

- Every verdict shows confidence and links. Never a bare "FAKE".
- "Unverified" is a normal outcome and must not feel like a failure.
- Disclaimer on the result card: "Automated check. Not a final judgment."
- Report button: "This verdict looks wrong". Store those cases, add them to your test set.
- Keep a visible list of sources the verdict used.
- Do not store users' links longer than needed. State what you keep in the privacy policy.

---

## 13. Timeline

| Days | Work | Done when |
|---|---|---|
| 1 | Accounts and keys | All keys in a password manager |
| 2 to 6 | Backend and 20-video test set | Curl returns a sane verdict for most test videos |
| 7 to 11 | Basic app, share target | End-to-end check works on your phone |
| 11 onward | Closed test starts (Play) | 12 testers opted in, clock running |
| 12 to 18 | Floating dot, Instagram detection | Dot appears over Instagram and result card works |
| 19 to 23 | Rewarded ads, SSV, limits | Second check of the day needs an ad |
| 24 to 30 | Fix bugs from testers, tune prompts | Test set results acceptable |
| ~Day 28 and after | Apply for production | App live in India |

---

## 14. Phase 2 features (after launch)

- Pay to skip ads: Play Billing one-time pack (for example 10 checks). Play takes a commission; there is no extra fee.
- Telugu and Hindi explanations.
- A cache: if the same reel link was already checked today, return the stored verdict without spending a search. This saves your free quotas and is the single best cost saver.
- Move to paid tiers only when ad income actually covers the per-check cost.

---

## 15. Known risks at a glance

| Risk | Why it matters | Mitigation |
|---|---|---|
| Instagram blocks downloads | Core input may fail | Video-file path as primary, test on day 2 |
| Instagram terms | Downloading and automated access may violate them | Keep it user-initiated, store nothing, take legal advice before scaling |
| Wrong verdict on real news | Reputation damage | Default to Unverified, show evidence, test set |
| Free quotas run out | Service stops mid-month | Cache, check cheap sources first, show a friendly "busy" message |
| Play rejects overlay or usage access | Cannot publish | Clear permission explanations, honest declarations, a fallback share-sheet mode that needs neither |
| Gemini free tier trains on prompts | Privacy exposure | State it in the privacy policy; consider paid tier before real scale |
| Render cold start | First check feels slow | Wake call on app launch, loading message |

---

## Sources checked while writing this

- Gemini API rate limits and free tier notes: ai.google.dev/gemini-api/docs/rate-limits and third-party summaries (figures differ by source; use your AI Studio console)
- SerpApi free plan (250 searches a month) and Google Lens needing public image URLs: serpapi.com and SerpApi's Google Lens write-up
- Google Fact Check Tools API (claims search and image search): developers.google.com/fact-check/tools/api
- Render free tier (15-minute spin-down, 750 hours, ephemeral disk): render.com/docs/free
- Google Play fee and 12-tester, 14-day rule for personal accounts created after 13 Nov 2023: Play Console help and developer guides
- AdMob rewarded ads, test ad unit ID, server-side verification: developers.google.com/admob and support.google.com/admob

Not independently verified and flagged in the text: yt-dlp behavior on Instagram from Render's IPs, Supabase free-project pausing rules, exact Play permission-declaration requirements for overlay and usage access.
