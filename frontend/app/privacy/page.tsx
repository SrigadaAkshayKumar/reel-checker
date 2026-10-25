import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy & terms" };

export default function Privacy() {
  return (
    <article className="card stack">
      <h1>Privacy &amp; terms</h1>
      <p className="sub">Plain language, short. Last updated October 2026.</p>

      <h2>What happens to your video</h2>
      <ul>
        <li>Your upload is used only to run the check, then deleted, whether the check succeeds or fails.</li>
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
        No account, no name, no phone number. To limit abuse we count checks per internet address per day, stored
        only as a one-way scrambled code. Feedback you send is stored with the report, not with you.
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
        Upload only videos you are allowed to share, and don&apos;t use this service to harass anyone. We don&apos;t
        download anything from Instagram or other platforms ourselves; we only check what you upload.
      </p>
    </article>
  );
}
