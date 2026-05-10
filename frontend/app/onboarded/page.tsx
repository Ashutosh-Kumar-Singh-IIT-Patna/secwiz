"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { Stepper } from "@/components/Stepper";
import { ApiError, triggerRun } from "@/lib/api";
import type { TriggerResponse } from "@/lib/types";

export default function OnboardedPage() {
  return (
    <Suspense fallback={<div className="text-sm text-ink-300">Loading…</div>}>
      <OnboardedInner />
    </Suspense>
  );
}

function OnboardedInner() {
  const params = useSearchParams();
  const userId = params.get("user_id") || "";
  const email = params.get("email") || "your inbox";
  const depCount = params.get("deps") || "?";

  const [triggering, setTriggering] = useState<boolean>(false);
  const [result, setResult] = useState<TriggerResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runTest = async () => {
    if (!userId) {
      setError("Missing user_id in the URL — go back through onboarding.");
      return;
    }
    setError(null);
    setTriggering(true);
    setResult(null);
    try {
      const out = await triggerRun(userId);
      setResult(out);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `Trigger failed (${err.status}): ${err.message}`
          : `Trigger failed: ${(err as Error).message}`,
      );
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div>
      <Stepper
        current={3}
        steps={["Email + deps", "Source preferences", "Confirmation"]}
      />
      <section className="space-y-6">
        <header>
          <h2 className="text-xl font-semibold text-ink-50">
            3. You’re all set
          </h2>
          <p className="mt-1 text-sm text-ink-300">
            We’ll check your{" "}
            <span className="font-mono text-ink-100">{depCount}</span>{" "}
            dependencies every hour and email{" "}
            <span className="font-mono text-ink-100">{email}</span> on
            high-confidence matches. Lower-confidence findings stay in the
            backend store; the dashboard for those lands in V2.
          </p>
        </header>

        <div className="rounded-lg border border-ink-700 bg-ink-800/40 px-4 py-3 text-xs">
          <span className="text-ink-400">User id:</span>{" "}
          <span className="font-mono text-ink-100">{userId || "(missing)"}</span>
        </div>

        <div className="rounded-lg border border-ink-700 bg-ink-800/30 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={triggering}
              onClick={runTest}
              className={[
                "rounded-md px-4 py-2 text-sm font-medium transition",
                triggering
                  ? "cursor-wait bg-ink-700 text-ink-400"
                  : "bg-emerald-500 text-ink-900 hover:bg-emerald-400",
              ].join(" ")}
            >
              {triggering ? "Running…" : "Send me a test alert"}
            </button>
            <p className="text-xs text-ink-400">
              Runs the full pipeline once. With{" "}
              <code className="font-mono">EMAIL_DRY_RUN=true</code>, alerts are
              logged on the backend instead of sent — handy for demos.
            </p>
          </div>
          {error && (
            <pre className="mt-3 whitespace-pre-wrap rounded-md border border-rose-500/30 bg-rose-500/5 p-2 text-xs text-rose-300">
              {error}
            </pre>
          )}
          {result && <RunCard result={result} />}
        </div>

        <div className="text-xs text-ink-400">
          <Link href="/onboard" className="underline underline-offset-2">
            ← Tweak the watchlist or sources
          </Link>
        </div>
      </section>
    </div>
  );
}

function RunCard({ result }: { result: TriggerResponse }) {
  const stats = result.run.stats || {};
  const cells: Array<[string, number | string]> = [
    ["docs", stats.docs ?? "—"],
    ["candidates", stats.candidates ?? "—"],
    ["events", stats.events ?? "—"],
    ["alerts sent", stats.alerts_sent ?? 0],
    ["llm suppressed", stats.llm_suppressed ?? 0],
  ];
  const error = result.run.error;
  return (
    <div className="mt-3 space-y-2">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {cells.map(([label, value]) => (
          <div
            key={label}
            className="rounded-md border border-ink-800 bg-ink-900/60 px-3 py-2 text-center"
          >
            <div className="font-mono text-base text-ink-50">{value}</div>
            <div className="text-[10px] uppercase tracking-wide text-ink-400">
              {label}
            </div>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-ink-500">
        Started {fmt(result.run.started_at)} · Finished{" "}
        {fmt(result.run.finished_at)} · Run id{" "}
        <span className="font-mono text-ink-300">{result.run.id}</span>
      </p>
      {error && (
        <pre className="whitespace-pre-wrap rounded-md border border-rose-500/30 bg-rose-500/5 p-2 text-xs text-rose-300">
          {error}
        </pre>
      )}
    </div>
  );
}

function fmt(iso: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString();
  } catch {
    return iso;
  }
}
