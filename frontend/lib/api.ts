// Client for the FastAPI backend (backend/app/api/routes.py). Types mirror its JSON.

export type Verdict = "DEBUNKED" | "LIKELY_OLD_FOOTAGE" | "NO_CONTRADICTION_FOUND" | "UNVERIFIED";
export type JobStatus = "queued" | "running" | "done" | "failed";

export interface Job {
  job_id: string;
  status: JobStatus;
  step: string | null;
  steps: string[];
  queue_position: number | null;
  error: string | null;
  report_id: string | null;
  report_url: string | null;
  share_url: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cached?: boolean;
}

export interface Evidence {
  source: "fact_check" | "youtube" | "own_index" | "vision_web" | string;
  title: string;
  url?: string; // absent for footage seen in an early check that predates report links
  date?: string;
  similarity?: number;
  clip_similarity?: number;
  matched_frame?: number;
  publisher?: string;
  rating?: string;
  relevance?: number;
  thumbnail_url?: string;
  notes?: string;
  supports: "debunk" | "earlier_footage" | "lead";
}

export interface Claim {
  claim_text: string;
  event: string;
  location: string;
  claimed_date: string | null;
  recency: "current" | "dated" | "none";
  keywords: string[];
  language: string;
  visual_description: string;
  engine: string;
}

export interface Check {
  name: string;
  status: "ok" | "skipped" | "failed" | "quota" | "not_needed";
  detail: string;
  seconds: number;
}

export interface Report {
  report_id: string;
  job_id: string;
  created_at: string;
  reference_date: string;
  input: { duration: number; width: number; height: number; has_audio: boolean };
  caption: string;
  claim: Claim;
  transcript: { text: string; language: string; confidence: number | null; engine: string } | null;
  onscreen_text: string[];
  verdict: Verdict;
  verdict_label: string;
  confidence: number;
  reasons: string[];
  summary: string;
  summary_local: string;
  evidence: Evidence[];
  comparisons: { image: string; image_url: string; evidence_url: string; similarity: number }[];
  keyframes: string[];
  checks: Check[];
  partial: boolean;
  manual_links: { name: string; url: string; how: string }[];
  disclaimer: string;
  share_url: string;
}

/** Base URL of the backend as the browser sees it (baked in at build time). */
export const PUBLIC_API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

/** Base URL for server-side calls; may be an internal address. */
export function serverApiUrl(): string {
  return (process.env.API_URL || PUBLIC_API_URL).replace(/\/$/, "");
}

/** Backend paths such as /api/reports/x/files/compare_1.jpg → absolute public URL. */
export function apiAsset(path: string): string {
  return /^https?:\/\//.test(path) ? path : `${PUBLIC_API_URL}${path}`;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

/** Turns the backend's {"detail": {"code", "message"}} (or FastAPI's plain detail) into an ApiError. */
export function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    const d = detail as { code?: string; message: string };
    return new ApiError(status, d.code || "error", d.message);
  }
  if (typeof detail === "string") return new ApiError(status, "error", detail);
  if (status === 0) return new ApiError(0, "network", "Could not reach the server. Check your connection and try again.");
  return new ApiError(status, "error", "Something went wrong. Please try again.");
}

async function parse<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => null);
  if (!res.ok) throw toApiError(res.status, body);
  return body as T;
}

export async function getJob(jobId: string, signal?: AbortSignal): Promise<Job> {
  return parse<Job>(await fetch(`${PUBLIC_API_URL}/api/jobs/${jobId}`, { cache: "no-store", signal }));
}

/** Server-side. Returns null for an unknown report. */
export async function fetchReport(id: string): Promise<Report | null> {
  const res = await fetch(`${serverApiUrl()}/api/reports/${encodeURIComponent(id)}`);
  if (res.status === 404) return null;
  return parse<Report>(res);
}

export async function sendFeedback(reportId: string, correct: boolean, note = ""): Promise<void> {
  await parse(await fetch(`${PUBLIC_API_URL}/api/reports/${reportId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ correct, note }),
  }));
}

export interface UploadInput {
  file: File;
  caption?: string;
  postedDate?: string;
}

/** Multipart upload with progress (fetch has no upload progress events, so XHR). */
export function uploadReel(input: UploadInput, onProgress?: (fraction: number) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", input.file);
    if (input.caption?.trim()) form.append("caption", input.caption.trim());
    if (input.postedDate) form.append("posted_date", input.postedDate);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${PUBLIC_API_URL}/api/analyze`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as Job);
      else reject(toApiError(xhr.status, xhr.response));
    };
    xhr.onerror = () => reject(toApiError(0, null));
    xhr.send(form);
  });
}
