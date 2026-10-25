import type { Metadata, Viewport } from "next";
import Link from "next/link";

import "./globals.css";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: { default: "Reel Fact-Checker: is this reel old footage?", template: "%s · Reel Fact-Checker" },
  description:
    "Upload a reel and find out whether the footage is really from when and where it claims, with sources.",
  openGraph: { siteName: "Reel Fact-Checker", type: "website" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#171a21" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <div className="container">
            <Link href="/" className="brand" aria-label="Reel Fact-Checker home">
              <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
                <rect width="32" height="32" rx="8" fill="var(--accent)" />
                <path d="M9 9h10l4 4v10H9z" fill="none" stroke="var(--on-accent)" strokeWidth="2.2" strokeLinejoin="round" />
                <path d="m12.5 17 2.5 2.5 4.5-5" fill="none" stroke="var(--on-accent)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Reel Fact-Checker
            </Link>
            <nav aria-label="Main">
              <Link href="/">Check a reel</Link>
              <Link href="/privacy">Privacy</Link>
            </nav>
          </div>
        </header>
        <main>
          <div className="container">{children}</div>
        </main>
        <footer className="site-footer">
          <div className="container">
            <p>Automated checks can be wrong. We report evidence about footage, never about the people who share it.</p>
            <p>
              <Link href="/privacy">Privacy &amp; terms</Link>
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
