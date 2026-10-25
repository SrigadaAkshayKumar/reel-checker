import type { Metadata } from "next";
import { cacheLife } from "next/cache";
import { notFound } from "next/navigation";

import ReportView from "@/components/report/ReportView";
import { apiAsset, fetchReport } from "@/lib/api";
import { VERDICTS } from "@/lib/present";

const ID = /^[0-9a-f]{12}$/;
const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");

// A finished report never changes, so cache it hard. Unknown ids are rejected before the call.
async function getReport(id: string) {
  "use cache";
  cacheLife("days");
  return fetchReport(id);
}

async function load(params: Promise<{ id: string }>) {
  const { id } = await params;
  if (!ID.test(id)) notFound();
  const report = await getReport(id);
  if (!report) notFound();
  return report;
}

export async function generateMetadata({ params }: PageProps<"/r/[id]">): Promise<Metadata> {
  const r = await load(params);
  const label = VERDICTS[r.verdict].label;
  const description = (r.summary.split("\n")[0] || VERDICTS[r.verdict].meaning).slice(0, 200);
  const image = r.comparisons[0]?.image_url || r.keyframes[0];
  return {
    title: `${label}: ${r.claim.claim_text || "reel check"}`.slice(0, 90),
    description,
    alternates: { canonical: `/r/${r.report_id}` },
    openGraph: {
      title: `Reel check: ${label}`,
      description,
      type: "article",
      url: `/r/${r.report_id}`,
      images: image ? [{ url: apiAsset(image) }] : undefined,
    },
    twitter: { card: image ? "summary_large_image" : "summary", title: `Reel check: ${label}`, description },
  };
}

export default async function ReportPage({ params }: PageProps<"/r/[id]">) {
  const report = await load(params);
  return <ReportView report={report} shareUrl={`${siteUrl}/r/${report.report_id}`} />;
}
