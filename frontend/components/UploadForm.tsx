"use client";

import { useRouter } from "next/navigation";
import { useId, useState, useSyncExternalStore } from "react";

import { ApiError, uploadReel } from "@/lib/api";
import { MAX_UPLOAD_MB, MAX_VIDEO_SECONDS, checkFile } from "@/lib/present";

import styles from "./UploadForm.module.css";

function readDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    const done = (value: number | null) => {
      URL.revokeObjectURL(url);
      resolve(value);
    };
    video.onloadedmetadata = () => done(Number.isFinite(video.duration) ? video.duration : null);
    video.onerror = () => done(null); // some formats (e.g. MKV on iOS) can't be previewed; the server decides
    video.src = url;
  });
}

const noSubscribe = () => () => {};
const todayIso = () => new Date().toISOString().slice(0, 10);

function formatSize(bytes: number): string {
  return bytes > 1024 * 1024 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

export default function UploadForm() {
  const router = useRouter();
  const ids = useId();
  const [file, setFile] = useState<File | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const [caption, setCaption] = useState("");
  const [posted, setPosted] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  // Client-only: "today" must not be frozen into the prerendered page.
  const today = useSyncExternalStore(noSubscribe, todayIso, () => undefined);

  async function choose(f: File | undefined) {
    setError(null);
    if (!f) return;
    const problem = checkFile(f);
    if (problem) {
      setFile(null);
      setError(problem);
      return;
    }
    const seconds = await readDuration(f);
    if (seconds !== null && seconds > MAX_VIDEO_SECONDS + 0.5) {
      setFile(null);
      setError(`This video is ${Math.round(seconds)} seconds long. The limit is ${MAX_VIDEO_SECONDS} seconds.`);
      return;
    }
    setFile(f);
    setDuration(seconds);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || progress !== null) return;
    setError(null);
    setProgress(0);
    try {
      const job = await uploadReel({ file, caption, postedDate: posted || undefined }, setProgress);
      if (job.status === "done" && job.report_id) router.push(`/r/${job.report_id}`);
      else router.push(`/check/${job.job_id}`);
    } catch (err) {
      setProgress(null);
      setError(err instanceof ApiError ? err.message : "Upload failed. Please try again.");
    }
  }

  const uploading = progress !== null;

  return (
    <form className={`card ${styles.form}`} onSubmit={submit} noValidate>
      <label
        htmlFor={`${ids}-file`}
        className={`${styles.drop} ${dragging ? styles.dragging : ""} ${file ? styles.chosen : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          choose(e.dataTransfer.files?.[0]);
        }}
      >
        <svg width="28" height="28" viewBox="0 0 24 24" aria-hidden="true" className={styles.icon}>
          <path d="M12 16V4m0 0-4 4m4-4 4 4M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {file ? (
          <span>
            <strong className={styles.fileName}>{file.name}</strong>
            <span className="sub">
              {formatSize(file.size)}
              {duration !== null && ` · ${Math.round(duration)} s`} · tap to change
            </span>
          </span>
        ) : (
          <span>
            <strong>Choose the reel</strong>
            <span className="sub">
              or a screen recording of it · up to {MAX_VIDEO_SECONDS} s and {MAX_UPLOAD_MB} MB
            </span>
          </span>
        )}
        <input
          id={`${ids}-file`}
          className="visually-hidden"
          type="file"
          accept="video/*,.mp4,.mov,.m4v,.webm,.mkv,.3gp"
          disabled={uploading}
          onChange={(e) => choose(e.target.files?.[0])}
        />
      </label>

      <details className={styles.more}>
        <summary>Add the caption and date (optional, gives better results)</summary>
        <label htmlFor={`${ids}-caption`}>Caption of the post</label>
        <textarea
          id={`${ids}-caption`}
          rows={3}
          maxLength={2200}
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          placeholder="Paste the text that came with the reel, in any language"
          disabled={uploading}
        />
        <label htmlFor={`${ids}-posted`}>Date it was posted</label>
        <input
          id={`${ids}-posted`}
          type="date"
          max={today}
          value={posted}
          onChange={(e) => setPosted(e.target.value)}
          disabled={uploading}
        />
      </details>

      {error && (
        <p className={`alert tone-bad ${styles.error}`} role="alert">
          {error}
        </p>
      )}

      {uploading ? (
        <div className={styles.progress} role="status" aria-live="polite">
          <div className={styles.bar}>
            <span style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
          </div>
          <span className="sub">
            {progress !== null && progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Starting the check…"}
          </span>
        </div>
      ) : (
        <button type="submit" className="btn btn-primary btn-block" disabled={!file}>
          Check this reel
        </button>
      )}
      <p className={`sub small ${styles.note}`}>
        The video is deleted right after the check. We keep only fingerprints and the report.
      </p>
    </form>
  );
}
