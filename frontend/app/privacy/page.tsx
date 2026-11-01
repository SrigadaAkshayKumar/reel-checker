import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy & terms" };

export default function Privacy() {
  return (
    <article className="card stack">
      <h1>Privacy &amp; terms</h1>
      <p className="sub">Plain language, short. Covers this website and the Android app. Last updated November 2026.</p>

      <h2>What happens to your video</h2>
      <ul>
        <li>Your upload is used only to run the check, then deleted, whether the check succeeds or fails.</li>
        <li>
          In the app you can paste a reel link instead. We then fetch that one public reel, once, only to check it,
          and delete it the same way. We keep a one-way scrambled code of the link so the same reel gets the same
          answer without fetching it again, not the link itself.
        </li>
        <li>
          We keep the report, a few small still frames from the video (shown on the report page and used for
          reverse image search), and digital fingerprints of the frames. Fingerprints let us spot the same footage
          when someone else uploads it, without keeping the video.
        </li>
        <li>
          To read the claim, frames and audio are sent to Google&apos;s Gemini service. On Google&apos;s free tier,
          Google may use that content to improve its products. Don&apos;t upload anything private.
        </li>
        <li>Report links are public: anyone with the link can see the report.</li>
      </ul>

      <h2>What we store about you</h2>
      <p>
        No name, no email, no phone number. To limit abuse we count checks per internet address per day, stored
        only as a one-way scrambled code. Feedback you send is stored with the report, not with you.
      </p>
      <p>
        The app creates an anonymous ID on first launch. With it we count your free check for the day and the
        checks you earned by watching ads. It isn&apos;t linked to your name or Google account.
      </p>

      <h2>Ads in the app</h2>
      <p>
        The first check each day is free. Another check needs one short video ad, which you choose to watch. Ads
        come from Google AdMob, which may use your device&apos;s advertising ID and collect usage data under
        Google&apos;s own privacy policy; you can reset or delete that ID in your phone&apos;s settings. When you
        finish an ad, Google tells our server your anonymous app ID, so we can add the check. If a check fails, or
        some of our searches couldn&apos;t run, you get the check back.
      </p>

      <h2>What a result means</h2>
      <ul>
        <li>Results are automated and can be wrong. They show evidence about footage, nothing more.</li>
        <li>
          “No contradiction found” never means a reel is real. It means we didn&apos;t find earlier copies or
          fact-checks.
        </li>
        <li>We never say anything about the people or accounts who shared a reel.</li>
        <li>If a result is wrong, use “Was this correct?” on the report. We review those reports.</li>
      </ul>

      <h2>Your part</h2>
      <p>
        Upload or paste only reels you are allowed to share, and don&apos;t use this service to harass anyone. We
        only fetch a reel when you paste its link, and never sign in to Instagram.
      </p>
    </article>
  );
}
