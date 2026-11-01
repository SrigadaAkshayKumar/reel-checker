# Reel Check for Android

Kotlin app for the backend in `../backend` (API: [`../docs/mobile-api.md`](../docs/mobile-api.md)). Plan and Play
Store steps: [`../docs/android-build-guide.md`](../docs/android-build-guide.md).

| Part | File |
|---|---|
| Main screen: paste link, choose a video, result card, ad button, floating-button settings (Compose) | `app/…/MainActivity.kt` |
| Instagram Share sheet (link or video) | `ShareReceiverActivity.kt` |
| Floating button over Instagram: dot, input card, result card at 75% height (classic Views) | `OverlayService.kt` |
| Rewarded ad in a transparent activity, SSV user id = the anonymous account | `Ads.kt` |
| Check flow shared by the screen and the button: free check → ad → wait for credit → retry | `CheckController.kt` |
| API client, polling, link parsing, wording (plain Kotlin, tested without Android) | `core/` |

The server decides what a check costs. The app never counts checks or grants credits: after an ad it waits for
the server's credit (Google calls the server, not the app).

## Build

Needs Android Studio (or the Android SDK) and JDK 17+.

```bash
./gradlew -p core test                  # logic tests, no Android SDK needed
./gradlew :app:assembleDebug            # app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:lintDebug
```

CI builds the debug APK on every push: *Actions → ci → the run → Artifacts → reel-check-debug-apk*. Install it on
a phone with "Install unknown apps" allowed for your file manager.

## Settings

Pass with `-P`, or put in `~/.gradle/gradle.properties` (not in the repo):

| Property | Default | |
|---|---|---|
| `reelApiUrl` | debug: `http://10.0.2.2:8000` (your computer, from the emulator); release: must be set | `https://api.yourdomain` |
| `reelSiteUrl` | `https://example.org` | the website, for the privacy link |
| `admobAppId` | Google's test app id | your AdMob app id (`ca-app-pub-…~…`) |
| `admobRewardedId` | Google's test rewarded unit | your rewarded unit id (`ca-app-pub-…/…`), also in the server's `ADMOB_AD_UNIT_IDS` |
| `releaseStoreFile`, `releaseStorePassword`, `releaseKeyAlias`, `releaseKeyPassword` | none | release signing |

Debug builds get the package `org.reelcheck.app.debug`, so they install next to a release build.

**Keep Google's test ad ids until release.** Never tap live ads on your own phone; AdMob suspends accounts for it.
Register your phone as a test device in AdMob to test with your real ad unit.

### Try it against your computer

```bash
cd ../backend && uvicorn app.main:app --host 0.0.0.0 --port 8000     # embedded worker
cd ../android && ./gradlew :app:installDebug                          # emulator running
```

On a real phone on the same Wi-Fi, use `-PreelApiUrl=http://<computer's LAN IP>:8000`. Ads stay off until the
server has `ADMOB_AD_UNIT_IDS`; the app then says to come back tomorrow instead of offering an ad.

## Release (Play Store)

```bash
keytool -genkeypair -v -keystore ~/reel-release.jks -alias reel -keyalg RSA -keysize 4096 -validity 10000
./gradlew :app:bundleRelease -PreelApiUrl=https://api.yourdomain -PreelSiteUrl=https://yourdomain \
  -PadmobAppId=ca-app-pub-…~… -PadmobRewardedId=ca-app-pub-…/… -PversionCode=2 \
  -PreleaseStoreFile=$HOME/reel-release.jks -PreleaseStorePassword=… -PreleaseKeyAlias=reel -PreleaseKeyPassword=…
```

Upload `app/build/outputs/bundle/release/app-release.aab`. Back up the keystore: losing it means you can no longer
update the app (unless you enrolled in Play App Signing, which Play Console offers on first upload: accept it).

Play Console declarations this app needs:

- **Foreground service (special use)**: "Shows a floating button over Instagram that the user taps to check a
  reel. Started only when the user turns it on; stopped from its notification." Play may ask for a short video
  of the feature.
- **Display over other apps** and **Usage access**: the same purpose; usage access only tells the app whether
  Instagram is on screen. Both are optional: links and videos can be checked from the Share sheet without them.
- **Data safety**: anonymous app id and daily check counts; links and videos sent for analysis and then deleted;
  advertising ID collected by AdMob. **Ads**: yes. Privacy policy: `https://yourdomain/privacy`.
- Target audience: adults (18+).
