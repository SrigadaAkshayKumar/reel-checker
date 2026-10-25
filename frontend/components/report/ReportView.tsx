/* eslint-disable @next/next/no-img-element -- images come from the backend host, known only at runtime */
import type { Evidence, Report } from "@/lib/api";
import { apiAsset } from "@/lib/api";
import {
  LANGUAGES, ROLE_LABELS, SOURCE_LABELS, VERDICTS, formatDate, percent, reverseSearchLinks, similarityText,
} from "@/lib/present";

import Feedback from "./Feedback";
import ShareBar from "./ShareBar";
import styles from "./report.module.css";

const RECENCY = { current: "presented as happening now", dated: "a specific past date", none: "no time given" };
const REVERSE_SEARCH = new Set(["Google Lens", "Yandex Images", "TinEye"]);

function EvidenceItem({ e }: { e: Evidence }) {
  const role = ROLE_LABELS[e.supports] || ROLE_LABELS.lead;
  const meta = [
    SOURCE_LABELS[e.source] || e.source,
    e.publisher,
    e.date && (e.source === "own_index" ? `first seen ${formatDate(e.date)}` : formatDate(e.date)),
    similarityText(e.similarity),
    e.rating && `rated “${e.rating}”`,
  ].filter(Boolean);
  return (
    <li className={styles.evidence}>
      <div className={styles.evidenceHead}>
        <a href={e.url} target="_blank" rel="nofollow noopener noreferrer">{e.title || e.url}</a>
        <span className={`tag tone-${role.tone}`}>{role.label}</span>
      </div>
      <p className="sub small">{meta.join(" · ")}</p>
    </li>
  );
}

export default function ReportView({ report: r, shareUrl }: { report: Report; shareUrl: string }) {
  const v = VERDICTS[r.verdict];
  const claim = r.claim.claim_text || "We couldn't tell what this reel claims.";
  const strong = r.evidence.filter((e) => e.supports !== "lead");
  const leads = r.evidence.filter((e) => e.supports === "lead");
  const frames = r.keyframes.slice(0, 3).map(apiAsset);
  // When frames are publicly reachable, the per-frame buttons replace the generic upload-it-yourself links.
  const framesSearchable = frames.length > 0 && reverseSearchLinks(frames[0]) !== null;
  const otherLinks = r.manual_links.filter((m) => !(framesSearchable && REVERSE_SEARCH.has(m.name)));
  const lang = LANGUAGES[r.claim.language] || r.claim.language;

  return (
    <article className="stack">
      <section className={`card ${styles.verdict}`} aria-labelledby="verdict">
        <p className="sub small">Reel check · {formatDate(r.created_at)}</p>
        <h1 id="verdict" className={`${styles.badge} tone-${v.tone}`}>{v.label}</h1>
        <p className={styles.meaning}>{v.meaning}</p>
        {r.verdict !== "UNVERIFIED" && (
          <div className={styles.confidence}>
            <span className="sub small">How sure we are</span>
            <div className={styles.meter} role="meter" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={Math.round(r.confidence * 100)} aria-label="Confidence">
              <span className={`tone-${v.tone}`} style={{ width: percent(r.confidence) }} />
            </div>
            <span className="small"><strong>{percent(r.confidence)}</strong></span>
          </div>
        )}
        {r.partial && (
          <p className="alert tone-muted small">
            Some searches couldn&apos;t run this time, so this report may be missing evidence.
          </p>
        )}
      </section>

      <section className="card" aria-labelledby="claim">
        <h2 id="claim">What the reel claims</h2>
        <p className={styles.claim}>{claim}</p>
        <dl className={styles.facts}>
          {r.claim.event && (<><dt>Event</dt><dd>{r.claim.event}</dd></>)}
          {r.claim.location && (<><dt>Place</dt><dd>{r.claim.location}</dd></>)}
          <dt>When</dt>
          <dd>{r.claim.claimed_date ? `${formatDate(r.claim.claimed_date)} (${RECENCY[r.claim.recency]})` : RECENCY[r.claim.recency]}</dd>
          {lang && (<><dt>Language</dt><dd>{lang}</dd></>)}
        </dl>
      </section>

      <section className="card" aria-labelledby="summary">
        <h2 id="summary">What we found</h2>
        <div className={styles.summary}>{r.summary}</div>
        {r.summary_local && (
          <div className={styles.summary} lang={r.claim.language || undefined}>{r.summary_local}</div>
        )}
      </section>

      {r.comparisons.length > 0 && (
        <section className="card" aria-labelledby="compare">
          <h2 id="compare">Side by side</h2>
          {r.comparisons.map((c) => (
            <figure key={c.image_url} className={styles.compare}>
              <img src={apiAsset(c.image_url)} alt="A frame from the reel next to the matching earlier footage" loading="lazy" />
              <figcaption className="sub small">
                Left: the reel. Right: <a href={c.evidence_url} target="_blank" rel="nofollow noopener noreferrer">the
                earlier copy</a> ({percent(c.similarity)} frame match).
              </figcaption>
            </figure>
          ))}
        </section>
      )}

      <section className="card" aria-labelledby="evidence">
        <h2 id="evidence">Evidence</h2>
        {strong.length === 0 && leads.length === 0 && <p className="sub">No related sources were found.</p>}
        {strong.length > 0 && <ul className={styles.evidenceList}>{strong.map((e) => <EvidenceItem key={e.url + e.source} e={e} />)}</ul>}
        {leads.length > 0 && (
          <details className={styles.leads} open={strong.length === 0}>
            <summary>{leads.length} related result{leads.length > 1 ? "s" : ""} that don&apos;t match</summary>
            <ul className={styles.evidenceList}>{leads.map((e) => <EvidenceItem key={e.url + e.source} e={e} />)}</ul>
          </details>
        )}
      </section>

      <section className="card" aria-labelledby="manual">
        <h2 id="manual">Check it yourself</h2>
        {frames.length > 0 && (
          <>
            <p className="sub">Search the web for these frames from the reel. Older copies are the giveaway.</p>
            <ul className={styles.frames}>
              {frames.map((src, i) => {
                const links = reverseSearchLinks(src);
                return (
                  <li key={src}>
                    <img src={src} alt={`Frame ${i + 1} from the reel`} loading="lazy" />
                    <div className={styles.frameLinks}>
                      {links ? links.map((l) => (
                        <a key={l.name} href={l.url} target="_blank" rel="noopener noreferrer">{l.name}</a>
                      )) : <a href={src} download>Download frame</a>}
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}
        <ul className={styles.links}>
          {otherLinks.map((m) => (
            <li key={m.name}>
              <a href={m.url} target="_blank" rel="noopener noreferrer">{m.name}</a> <span className="sub small">{m.how}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card" aria-labelledby="share">
        <h2 id="share">Share this check</h2>
        <p className="sub">Send it to the group where you saw the reel.</p>
        <ShareBar url={shareUrl} text={`Reel check: ${v.label}. ${claim.slice(0, 120)}`} />
      </section>

      <section className="card" aria-labelledby="feedback">
        <h2 id="feedback">Was this correct?</h2>
        <Feedback reportId={r.report_id} />
      </section>

      <details className={`card ${styles.tech}`}>
        <summary>Technical details</summary>
        <ul className="small">
          {r.reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
        <table className={styles.checks}>
          <caption className="visually-hidden">Checks that ran</caption>
          <thead><tr><th scope="col">Check</th><th scope="col">Result</th><th scope="col">Time</th></tr></thead>
          <tbody>
            {r.checks.map((c) => (
              <tr key={c.name}><td>{c.name}</td><td>{c.status}</td><td>{c.seconds ? `${c.seconds}s` : "-"}</td></tr>
            ))}
          </tbody>
        </table>
        {r.onscreen_text.length > 0 && <p className="small"><strong>On-screen text:</strong> {r.onscreen_text.join(" · ")}</p>}
        {r.transcript?.text && <p className="small"><strong>Speech:</strong> {r.transcript.text}</p>}
      </details>
    </article>
  );
}
