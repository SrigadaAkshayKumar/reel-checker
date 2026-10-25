import UploadForm from "@/components/UploadForm";
import { VERDICTS } from "@/lib/present";

import styles from "./home.module.css";

const STEPS = [
  { title: "Upload the reel", body: "Save it or screen-record it, then upload it here. Add the caption if you have it." },
  { title: "We look for its past", body: "We read the claim, then search fact-checks and earlier uploads of the same footage." },
  { title: "Get the evidence", body: "A verdict with sources and side-by-side frames, in about a minute. Share it before the reel spreads." },
];

export default function Home() {
  return (
    <div className="stack">
      <section className={styles.hero}>
        <h1>Is this reel old footage?</h1>
        <p className="lede">
          Many “breaking news” reels reuse videos from years ago. Upload one and see where the footage really comes
          from, with sources you can check.
        </p>
      </section>

      <UploadForm />

      <section className={styles.section} aria-labelledby="how">
        <h2 id="how">How it works</h2>
        <ol className={styles.steps}>
          {STEPS.map((s, i) => (
            <li key={s.title} className="card">
              <span className={styles.num} aria-hidden="true">{i + 1}</span>
              <div>
                <h3>{s.title}</h3>
                <p className="sub">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className={styles.section} aria-labelledby="verdicts">
        <h2 id="verdicts">What the results mean</h2>
        <ul className={styles.verdicts}>
          {Object.entries(VERDICTS).map(([key, v]) => (
            <li key={key} className="card">
              <span className={`tag tone-${v.tone}`}>{v.label}</span>
              <p className="sub">{v.meaning}</p>
            </li>
          ))}
        </ul>
        <p className="sub">
          We never call a reel “100% real”. When nothing earlier turns up, we say so, and show you how to check further.
        </p>
      </section>
    </div>
  );
}
