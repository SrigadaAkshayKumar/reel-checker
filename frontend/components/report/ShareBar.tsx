"use client";

import { useState, useSyncExternalStore } from "react";

import { whatsappLink } from "@/lib/present";

import styles from "./report.module.css";

const noSubscribe = () => () => {};

export default function ShareBar({ url, text }: { url: string; text: string }) {
  const [copied, setCopied] = useState(false);
  // Native share exists only in some browsers; false on the server so hydration matches.
  const canShare = useSyncExternalStore(noSubscribe, () => "share" in navigator, () => false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy this link:", url);
    }
  }

  return (
    <div className={styles.share}>
      <a className="btn btn-primary" href={whatsappLink(`${text} ${url}`)} target="_blank" rel="noopener noreferrer">
        Share on WhatsApp
      </a>
      {canShare && (
        <button className="btn" type="button" onClick={() => navigator.share({ title: text, url }).catch(() => {})}>
          Share…
        </button>
      )}
      <button className="btn" type="button" onClick={copy} aria-live="polite">
        {copied ? "Link copied" : "Copy link"}
      </button>
    </div>
  );
}
