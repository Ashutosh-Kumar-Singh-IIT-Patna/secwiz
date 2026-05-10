import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Security Alerts Copilot",
  description:
    "Real-time breach and vulnerability alerts for the dependencies you actually run.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-ink-900 text-ink-100 antialiased">
        <div className="mx-auto flex min-h-screen max-w-3xl flex-col px-6 pb-16 pt-10">
          <header className="mb-10 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-300">
                <span className="text-sm font-semibold tracking-wide">SA</span>
              </div>
              <div>
                <p className="text-base font-semibold leading-tight text-ink-50">
                  Security Alerts Copilot
                </p>
                <p className="text-xs text-ink-300">
                  v1 — hourly checks, email-only
                </p>
              </div>
            </div>
            <BackendBadge />
          </header>
          <main className="flex-1">{children}</main>
          <footer className="mt-10 text-xs text-ink-400">
            Built on Anakin Wire / Agentic Search / URL Scraper · OSV · NVD ·
            Gemini judge.
          </footer>
        </div>
      </body>
    </html>
  );
}

function BackendBadge() {
  // Server component — read once at request time. Keeps the indicator
  // honest when running in dev mode against a possibly-down backend.
  const url = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
  return (
    <span className="font-mono text-[11px] text-ink-400">
      api: <span className="text-ink-200">{url}</span>
    </span>
  );
}
