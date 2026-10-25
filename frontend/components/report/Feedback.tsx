"use client";

import { useId, useState } from "react";

import { sendFeedback } from "@/lib/api";

export default function Feedback({ reportId }: { reportId: string }) {
  const id = useId();
  const [state, setState] = useState<"ask" | "explain" | "sending" | "sent" | "error">("ask");
  const [note, setNote] = useState("");

  async function send(correct: boolean) {
    setState("sending");
    try {
      await sendFeedback(reportId, correct, correct ? "" : note);
      setState("sent");
    } catch {
      setState("error");
    }
  }

  if (state === "sent") return <p className="sub" role="status">Thank you. Every answer helps us get better.</p>;

  return (
    <div>
      {(state === "ask" || state === "error") && (
        <div className="row">
          <button className="btn" type="button" onClick={() => send(true)}>Yes</button>
          <button className="btn" type="button" onClick={() => setState("explain")}>No, report a mistake</button>
        </div>
      )}
      {(state === "explain" || state === "sending") && (
        <div>
          <label htmlFor={id}>What is wrong? (optional)</label>
          <textarea id={id} rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)}
            placeholder="For example: this video really is from today, here is a news link…" />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn-primary" type="button" disabled={state === "sending"} onClick={() => send(false)}>
              Send
            </button>
            <button className="btn" type="button" onClick={() => setState("ask")}>Cancel</button>
          </div>
        </div>
      )}
      {state === "error" && <p className="alert tone-bad" role="alert" style={{ marginTop: 8 }}>Couldn&apos;t send. Please try again.</p>}
    </div>
  );
}
