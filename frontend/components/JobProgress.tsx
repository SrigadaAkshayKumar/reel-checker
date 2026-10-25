"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, getJob, type Job } from "@/lib/api";
import { STEP_LABELS } from "@/lib/present";

import styles from "./JobProgress.module.css";

const POLL_MS = 1500;

export default function JobProgress() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(null);
  const [problem, setProblem] = useState<{ fatal: boolean; message: string } | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    const started = Date.now();
    const tick = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);

    async function poll() {
      try {
        const next = await getJob(jobId, controller.signal);
        failures = 0;
        setProblem(null);
        setJob(next);
        if (next.status === "done" && next.report_id) {
          router.replace(`/r/${next.report_id}`);
          return;
        }
        if (next.status === "failed") return;
      } catch (err) {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setProblem({ fatal: true, message: "We couldn't find this check. The link may be wrong or expired." });
          return;
        }
        failures += 1;
        if (failures >= 3) setProblem({ fatal: false, message: "Connection lost. Still trying…" });
      }
      timer = setTimeout(poll, POLL_MS * Math.min(1 + failures, 5));
    }
    poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
      clearInterval(tick);
    };
  }, [jobId, router]);

  if (problem?.fatal) {
    return (
      <div className="card stack">
        <h1>Check not found</h1>
        <p>{problem.message}</p>
        <Link href="/" className="btn btn-primary">Check a reel</Link>
      </div>
    );
  }

  if (job?.status === "failed") {
    return (
      <div className="card stack">
        <h1>We couldn&apos;t check this reel</h1>
        <p className="alert tone-bad" role="alert">{job.error || "Something went wrong."}</p>
        <Link href="/" className="btn btn-primary">Try another reel</Link>
      </div>
    );
  }

  const steps = (job?.steps || Object.keys(STEP_LABELS)).filter((s) => s !== "done");
  const current = job?.status === "running" ? steps.indexOf(job.step || "") : -1;

  return (
    <div className="card">
      <h1 className={styles.title}>Checking the reel…</h1>
      <p className="sub" role="status" aria-live="polite">
        {!job && "Connecting…"}
        {job?.status === "queued" &&
          (job.queue_position && job.queue_position > 1
            ? `Waiting in line: ${job.queue_position - 1} ahead of you.`
            : "Starting shortly…")}
        {job?.status === "running" && (STEP_LABELS[job.step || ""] || "Working") + "…"}
        {job?.status === "done" && "Done. Opening the report…"}
      </p>

      <ol className={styles.steps}>
        {steps.map((s, i) => {
          const state = job?.status === "done" || i < current ? "done" : i === current ? "active" : "todo";
          return (
            <li key={s} className={styles[state]} aria-current={state === "active" ? "step" : undefined}>
              <span className={styles.dot} aria-hidden="true">
                {state === "done" ? "✓" : i + 1}
              </span>
              <span>{STEP_LABELS[s] || s}</span>
              <span className="visually-hidden">
                {state === "done" ? " (done)" : state === "active" ? " (in progress)" : ""}
              </span>
            </li>
          );
        })}
      </ol>

      <p className="sub small">
        Usually under a minute{elapsed > 0 ? ` · ${elapsed} s so far` : ""}. You can leave this page open; the report
        opens by itself.
      </p>
      {problem && <p className="alert tone-warn">{problem.message}</p>}
    </div>
  );
}
