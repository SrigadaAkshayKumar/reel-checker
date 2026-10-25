// Display helpers: verdict wording, step names, evidence labels, reverse-image-search links.
import type { Evidence, Verdict } from "./api";

export type Tone = "bad" | "warn" | "info" | "muted";

// "No contradiction" is neutral blue, never green: it is not a "real" stamp.
export const VERDICTS: Record<Verdict, { label: string; tone: Tone; meaning: string }> = {
  DEBUNKED: {
    label: "Debunked",
    tone: "bad",
    meaning: "Fact-checkers have already reviewed this claim and rated it false or misleading.",
  },
  LIKELY_OLD_FOOTAGE: {
    label: "Likely old footage",
    tone: "warn",
    meaning: "The same or very similar footage was online before the date the reel claims.",
  },
  NO_CONTRADICTION_FOUND: {
    label: "No contradiction found",
    tone: "info",
    meaning: "Nothing earlier turned up. That is not proof the reel is real.",
  },
  UNVERIFIED: {
    label: "Unverified",
    tone: "muted",
    meaning: "Not enough information to judge either way.",
  },
};

export const STEP_LABELS: Record<string, string> = {
  extracting: "Pulling frames and audio",
  transcribing: "Listening and reading on-screen text",
  understanding: "Working out what the reel claims",
  searching: "Searching for earlier copies and fact-checks",
  comparing: "Comparing the evidence",
  done: "Report ready",
};

export const SOURCE_LABELS: Record<string, string> = {
  fact_check: "Fact-check",
  youtube: "YouTube",
  own_index: "Known footage",
  vision_web: "Web image match",
};

export const ROLE_LABELS: Record<Evidence["supports"], { label: string; tone: Tone }> = {
  debunk: { label: "Fact-check", tone: "bad" },
  earlier_footage: { label: "Earlier footage", tone: "warn" },
  lead: { label: "Lead", tone: "muted" },
};

export const LANGUAGES: Record<string, string> = {
  te: "Telugu", hi: "Hindi", en: "English", ta: "Tamil", kn: "Kannada", ml: "Malayalam", mr: "Marathi",
  bn: "Bengali", gu: "Gujarati", pa: "Punjabi", ur: "Urdu", or: "Odia",
};

/** Same threshold as backend WEAK_SIMILARITY: below it, frames do not match. */
export const MATCH_THRESHOLD = 0.8;

export function percent(x: number): string {
  return `${Math.round(x * 100)}%`;
}

/** "a 0.72 similarity" reads like a partial match to most people, so below the threshold say so plainly. */
export function similarityText(sim: number | undefined): string | null {
  if (sim === undefined || sim === null) return null;
  return sim >= MATCH_THRESHOLD ? `${percent(sim)} frame match` : "frames do not match";
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** Reverse image search for a publicly reachable frame URL. Null when the URL is local (the services can't fetch it). */
export function reverseSearchLinks(imageUrl: string): { name: string; url: string }[] | null {
  let host: string;
  try {
    host = new URL(imageUrl).hostname;
  } catch {
    return null;
  }
  if (host === "localhost" || host === "127.0.0.1" || host.endsWith(".local") || /^(10|192\.168)\./.test(host)) {
    return null;
  }
  const u = encodeURIComponent(imageUrl);
  return [
    { name: "Google Lens", url: `https://lens.google.com/uploadbyurl?url=${u}` },
    { name: "Yandex", url: `https://yandex.com/images/search?rpt=imageview&url=${u}` },
    { name: "TinEye", url: `https://tineye.com/search?url=${u}` },
  ];
}

export const MAX_UPLOAD_MB = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB || 50);
export const MAX_VIDEO_SECONDS = Number(process.env.NEXT_PUBLIC_MAX_VIDEO_SECONDS || 90);

/** Quick checks before uploading; the backend checks again. */
export function checkFile(file: { name: string; size: number; type: string }): string | null {
  const ext = file.name.toLowerCase().split(".").pop() || "";
  const okExt = ["mp4", "mov", "m4v", "webm", "mkv", "3gp"].includes(ext);
  if (!okExt && !file.type.startsWith("video/")) return "Choose a video file (MP4, MOV, WEBM, MKV or 3GP).";
  if (!okExt) return "This video format isn't supported. Use MP4, MOV, WEBM, MKV or 3GP.";
  if (file.size === 0) return "This file is empty.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `The file is larger than ${MAX_UPLOAD_MB} MB.`;
  return null;
}

export function whatsappLink(text: string): string {
  return `https://wa.me/?text=${encodeURIComponent(text)}`;
}
