"use client";

import Link from "next/link";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="card stack">
      <h1>Something went wrong</h1>
      <p>We couldn&apos;t load this page. The service may be busy; please try again in a moment.</p>
      <div className="row">
        <button className="btn btn-primary" type="button" onClick={reset}>Try again</button>
        <Link href="/" className="btn">Home</Link>
      </div>
    </div>
  );
}
