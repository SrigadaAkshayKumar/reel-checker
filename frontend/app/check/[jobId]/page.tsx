import type { Metadata } from "next";
import { Suspense } from "react";

import JobProgress from "@/components/JobProgress";

export const metadata: Metadata = { title: "Checking…", robots: { index: false } };

export default function CheckPage() {
  return (
    <Suspense fallback={<div className="card skeleton" style={{ height: 320 }} />}>
      <JobProgress />
    </Suspense>
  );
}
