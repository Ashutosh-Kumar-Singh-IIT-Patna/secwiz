"use client";

import { useMemo, useState } from "react";

import { parseDeps } from "@/lib/parse-deps";
import {
  KNOWN_ECOSYSTEMS,
  type Dependency,
  type Ecosystem,
} from "@/lib/types";

interface Props {
  email: string;
  setEmail: (v: string) => void;
  deps: Dependency[];
  setDeps: (deps: Dependency[]) => void;
  onNext: () => void;
}

const SAMPLE_PACKAGE_JSON = `{
  "dependencies": {
    "lodash": "^4.17.21",
    "axios": "^1.6.0",
    "react": "^18.2.0"
  }
}`;

const SAMPLE_REQUIREMENTS = `requests==2.31.0
django>=4.2
fastapi==0.111.0
pydantic>=2.5`;

export function Step1EmailDeps({
  email,
  setEmail,
  deps,
  setDeps,
  onNext,
}: Props) {
  const [paste, setPaste] = useState<string>("");
  const [parseError, setParseError] = useState<string>("");

  const emailValid = useMemo(
    () => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()),
    [email],
  );
  const canContinue = emailValid && deps.length > 0;

  const handleParse = () => {
    setParseError("");
    const result = parseDeps(paste);
    if (!result.deps.length) {
      setParseError(
        result.warnings.join("\n") || "Couldn't find any dependencies in that text.",
      );
      return;
    }
    setDeps(mergeDeps(deps, result.deps));
  };

  const removeDep = (name: string, ecosystem: Ecosystem) =>
    setDeps(
      deps.filter(
        (d) => !(d.name === name && d.ecosystem === ecosystem),
      ),
    );

  const updateEcosystem = (idx: number, eco: Ecosystem) => {
    const next = [...deps];
    next[idx] = { ...next[idx], ecosystem: eco };
    setDeps(next);
  };

  return (
    <section className="space-y-6">
      <header>
        <h2 className="text-xl font-semibold text-ink-50">
          1. Where to send alerts &amp; what to watch
        </h2>
        <p className="mt-1 text-sm text-ink-300">
          Drop in your manifest (<code className="font-mono text-ink-200">package.json</code>,{" "}
          <code className="font-mono text-ink-200">requirements.txt</code>,{" "}
          <code className="font-mono text-ink-200">go.mod</code>,{" "}
          <code className="font-mono text-ink-200">Cargo.toml</code>) or just list package names — one per line.
        </p>
      </header>

      <label className="block">
        <span className="mb-1 block text-sm font-medium text-ink-200">
          Alert email
        </span>
        <input
          type="email"
          autoComplete="email"
          spellCheck={false}
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          className={[
            "w-full rounded-md border bg-ink-800/60 px-3 py-2 text-sm text-ink-50 placeholder-ink-500 outline-none transition",
            email && !emailValid
              ? "border-rose-500/50 focus:border-rose-400"
              : "border-ink-700 focus:border-emerald-500",
          ].join(" ")}
        />
        {email && !emailValid && (
          <span className="mt-1 block text-xs text-rose-400">
            That doesn’t look like a valid email.
          </span>
        )}
      </label>

      <div className="space-y-2">
        <span className="block text-sm font-medium text-ink-200">
          Dependencies
        </span>
        <textarea
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
          placeholder={`Paste a manifest, or list packages one per line.\n\nExample:\n\n${SAMPLE_REQUIREMENTS}`}
          rows={10}
          spellCheck={false}
          className="w-full rounded-md border border-ink-700 bg-ink-800/60 px-3 py-2 font-mono text-xs text-ink-50 placeholder-ink-500 outline-none transition focus:border-emerald-500"
        />
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button
            type="button"
            onClick={handleParse}
            className="rounded-md bg-emerald-500 px-3 py-1.5 font-medium text-ink-900 transition hover:bg-emerald-400"
          >
            Parse &amp; add
          </button>
          <button
            type="button"
            onClick={() => setPaste(SAMPLE_PACKAGE_JSON)}
            className="rounded-md border border-ink-700 px-3 py-1.5 text-ink-300 transition hover:border-ink-500 hover:text-ink-100"
          >
            Use sample package.json
          </button>
          <button
            type="button"
            onClick={() => setPaste(SAMPLE_REQUIREMENTS)}
            className="rounded-md border border-ink-700 px-3 py-1.5 text-ink-300 transition hover:border-ink-500 hover:text-ink-100"
          >
            Use sample requirements.txt
          </button>
          {deps.length > 0 && (
            <button
              type="button"
              onClick={() => setDeps([])}
              className="ml-auto rounded-md border border-ink-700 px-3 py-1.5 text-ink-400 transition hover:border-rose-500/50 hover:text-rose-300"
            >
              Clear watchlist
            </button>
          )}
        </div>
        {parseError && (
          <pre className="whitespace-pre-wrap rounded-md border border-rose-500/30 bg-rose-500/5 p-2 text-xs text-rose-300">
            {parseError}
          </pre>
        )}
      </div>

      {deps.length > 0 && (
        <div className="space-y-2">
          <span className="block text-sm font-medium text-ink-200">
            Watching ({deps.length})
          </span>
          <ul className="space-y-1">
            {deps.map((dep, idx) => (
              <li
                key={`${dep.ecosystem}:${dep.name}`}
                className="flex items-center gap-3 rounded-md border border-ink-800 bg-ink-800/40 px-3 py-2 text-sm"
              >
                <select
                  value={dep.ecosystem}
                  onChange={(e) =>
                    updateEcosystem(idx, e.target.value as Ecosystem)
                  }
                  className="rounded border border-ink-700 bg-ink-900 px-2 py-1 text-xs uppercase tracking-wide text-ink-200 focus:border-emerald-500 focus:outline-none"
                >
                  {KNOWN_ECOSYSTEMS.map((eco) => (
                    <option key={eco} value={eco}>
                      {eco}
                    </option>
                  ))}
                </select>
                <span className="font-mono text-ink-50">{dep.name}</span>
                {dep.version_spec && (
                  <span className="font-mono text-xs text-ink-400">
                    {dep.version_spec}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => removeDep(dep.name, dep.ecosystem)}
                  className="ml-auto rounded px-2 py-0.5 text-xs text-ink-400 transition hover:bg-rose-500/10 hover:text-rose-300"
                  aria-label={`Remove ${dep.name}`}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <footer className="flex justify-end pt-2">
        <button
          type="button"
          disabled={!canContinue}
          onClick={onNext}
          className={[
            "rounded-md px-4 py-2 text-sm font-medium transition",
            canContinue
              ? "bg-emerald-500 text-ink-900 hover:bg-emerald-400"
              : "cursor-not-allowed bg-ink-700 text-ink-400",
          ].join(" ")}
        >
          Continue →
        </button>
      </footer>
    </section>
  );
}

function mergeDeps(existing: Dependency[], incoming: Dependency[]): Dependency[] {
  const seen = new Set(existing.map((d) => `${d.ecosystem}:${d.name.toLowerCase()}`));
  const out = [...existing];
  for (const d of incoming) {
    const key = `${d.ecosystem}:${d.name.toLowerCase()}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push(d);
    }
  }
  return out;
}
