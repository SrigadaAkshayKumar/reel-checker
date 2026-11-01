# Android app: backend API

The Android app (plan: [`android-build-guide.md`](android-build-guide.md)) talks to the same backend as the
website. Where this build differs from the guide, on purpose:

| Guide | Here | Why |
|---|---|---|
| Supabase (auth, Postgres, storage) | Anonymous accounts and counters in our SQLite (`app_users`, `app_free`, `ssv_seen`) | One less service and key; data stays in the backed-up `data` volume |
| Render free tier | The Oracle VM from [`deploy.md`](deploy.md) | Render wipes the disk on restart (the footage index and reports would go) and sleeps after 15 min |
| `POST /check` waits for the verdict | `POST /api/app/check` returns a job; the app polls `/api/jobs/{id}` | An analysis takes 20-90 s; a held-open request breaks on mobile networks and timeouts |
| Gemini writes the verdict (incl. "Likely Authentic") | Code rules decide (`verdict.py`); Gemini extracts the claim and explains | Never says "real"; "Unverified" stays the default when evidence is thin |
| SerpApi Google Lens | Not yet. Own index → Fact Check → YouTube → Vision | Can be added as one more source later if the eval shows a gap |

Base URL: `https://API_DOMAIN`. All app calls except the AdMob callback send `Authorization: Bearer <token>`.
Errors are JSON: `{"detail": {"code": "...", "message": "..."}}`; show `message` to the user.

## 1. Sign in (first launch)

`POST /api/app/session` → `201`

```json
{"user_id": "3f9c0a1b2c3d4e5f", "token": "…", "free_left": 1, "ad_credits": 0, "can_check": true,
 "can_watch_ad": true, "resets_at": "2026-11-01T18:30:00+00:00", "ads_enabled": true}
```

Store `token` in `EncryptedSharedPreferences`. `user_id` is the AdMob **SSV user id**. Limited to
`APP_SESSIONS_PER_IP_DAY` new accounts per network per day (`429 rate_limited`). On any `401 signed_out`,
create a new session.

## 2. Allowance

`GET /api/app/me` → same fields as above. Call it on launch and after an ad.

- `free_left`: free checks left today (resets at `resets_at`, midnight India time)
- `ad_credits`: checks earned by watching ads, kept until used (at most `APP_MAX_AD_CREDITS`)
- `can_watch_ad`: false at the cap; don't offer an ad then

## 3. Check a reel

`POST /api/app/check`, multipart form:

| Field | |
|---|---|
| `url` | an Instagram reel link (`instagram.com/reel/…`, `/reels/`, `/p/`, `/tv/`; `?igsh=` is fine) |
| `file` | or the video file (MP4, MOV, WEBM, MKV, 3GP; ≤ 50 MB, ≤ 90 s) |
| `caption` | optional, the reel's caption |
| `posted_date` | optional, `YYYY-MM-DD` |

Responses:

| Status | Meaning | App does |
|---|---|---|
| `200` + `"cached": true` | This link or file was checked before. **Free.** `report_url` is ready | Show the report |
| `202` | Queued. `charged`: `free` or `ad`; the allowance fields are updated | Poll the job |
| `402 watch_ad` | No free check and no credit left. `detail.ads_enabled` false = ads not set up | "Watch a short ad to run another check" |
| `422 bad_link` | Not an Instagram reel link | Say so |
| `422 need_file` | Links are switched off on the server | Ask for the file |
| `400` / `413` / `415` | Bad, too big, or not a video | Show `message` |
| `429 rate_limited` | Too many checks from this network today | Show `message` |

Nothing is charged for a cached answer or a refused request.

## 4. Progress and the report

`GET /api/jobs/{job_id}` every 1.5 s until `status` is `done` or `failed`. `steps` lists the stages (link jobs
start with `downloading`), `step` is the current one.

- `done`: `GET {report_url}` for the report JSON; `share_url` is the public page to share.
- `failed` with `error_code: "need_file"`: Instagram didn't let the server fetch the reel. Show `error` and open
  the file picker. The check was **refunded**.
- `failed` otherwise: show `error`. Refunded too.

A report marked `partial` (some searches couldn't run, for example a used-up quota) is also refunded, so users
don't pay an ad for a degraded check.

Report JSON is described in `frontend/lib/api.ts` (`Report`). Show `verdict_label`, `confidence`, `summary`,
`evidence` links, `disclaimer`, and the "Was this correct?" button (`POST /api/reports/{id}/feedback`,
`{"correct": false, "note": "…"}`).

## 5. Rewarded ads (AdMob server-side verification)

1. AdMob → the rewarded ad unit → *Server-side verification* → callback URL
   `https://API_DOMAIN/api/admob/ssv`.
2. `.env` on the VM: `ADMOB_AD_UNIT_IDS=ca-app-pub-…/…` (comma-separate several). Callbacks for any other ad
   unit are refused, so another AdMob account can't mint credits by pointing its ads at us. Empty = ads off.
3. In the app, before showing the ad:
   `rewardedAd.setServerSideVerificationOptions(ServerSideVerificationOptions.Builder().setUserId(userId).build())`
4. On `onUserEarnedReward`, poll `GET /api/app/me` (every 2 s, up to 3 times) until `ad_credits` goes up, then
   retry the check. The credit arrives from Google's callback, not from the app.

The server checks Google's ECDSA signature against the keys at
`https://www.gstatic.com/admob/reward/verifier-keys.json` (cached a day, refetched for an unknown key id),
counts each `transaction_id` once, and returns `200` to every verified callback so AdMob doesn't retry.
During development use Google's test ad unit (`ca-app-pub-3940256099942544/5224354917`). Test ads may not trigger
the callback; check the callback with AdMob's *Verify URL* button, and the full flow with your real ad unit on a
registered test device (never tap live ads on your own phone).

## 6. Links: how fetching works, and the risk

The worker fetches a pasted link once with `yt-dlp` (no login, no cookies, only Instagram's extractor, only the
canonical `instagram.com/reel/<code>/` form, so a link can't make the server fetch anything else). The video is
deleted after analysis like an upload; the link itself is cleared from the job once fetched, and only a hash of
the reel code is kept for the cache.

- Instagram often refuses data-centre IPs. **Test on the VM first** (`docker compose exec worker python -m yt_dlp
  --simulate <a public reel link>`). If it fails most of the time, make the file path the main one in the app.
- Automated fetching may break Instagram's terms. It is user-initiated and nothing is stored, but take advice
  before scaling. `LINK_FETCH_ENABLED=false` switches it off; the app then gets `422 need_file`.
- Keep `yt-dlp` current: `docker compose build --pull` picks up the newest release (Instagram changes break old
  versions).

## Abuse limits, in short

Per account: `APP_FREE_CHECKS_PER_DAY` + earned credits. Per network: `APP_IP_DAILY_LIMIT` checks and
`APP_SESSIONS_PER_IP_DAY` new accounts a day (high, because Indian mobile carriers put many users behind one IP).
A user who reinstalls gets a new free check, at most `APP_SESSIONS_PER_IP_DAY` times per network. If that gets
abused, add Play Integrity attestation to `POST /api/app/session`.
