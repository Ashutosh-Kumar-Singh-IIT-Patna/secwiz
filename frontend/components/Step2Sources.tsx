"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError, api } from "@/lib/api";
import {
  FAMILY_LABELS,
  type FamilyConfig,
  type FamilyKey,
  type SourceConfig,
  type WireCatalogItem,
} from "@/lib/types";

interface Props {
  config: SourceConfig;
  setConfig: (cfg: SourceConfig) => void;
  onBack: () => void;
  onSubmit: () => Promise<void>;
  submitting: boolean;
  submitError: string | null;
}

const FAMILY_ORDER: FamilyKey[] = [
  "structured_intel",
  "news",
  "blogs",
  "social_media",
  "high_value_urls",
  "agentic_search",
];

// PLATFORM_FLOW V1 maps Wire-platform-style families to a checklist of
// catalog slugs. Categories below are advisory groupings — actual catalog
// records may carry a ``category`` value, in which case we use that.
const FAMILY_CATEGORIES: Record<FamilyKey, string[] | null> = {
  social_media: ["social", "social_media", "social-media"],
  news: ["news"],
  blogs: ["blog", "blogs", "developer", "developer-tools"],
  high_value_urls: null,
  agentic_search: null,
  structured_intel: null,
};

export function Step2Sources({
  config,
  setConfig,
  onBack,
  onSubmit,
  submitting,
  submitError,
}: Props) {
  const [catalog, setCatalog] = useState<WireCatalogItem[]>([]);
  const [catalogStatus, setCatalogStatus] =
    useState<"idle" | "loading" | "ok" | "error">("idle");
  const [catalogError, setCatalogError] = useState<string>("");

  // Bootstrap "all on" defaults the very first time we render.
  useEffect(() => {
    if (Object.keys(config.families).length > 0) return;
    const families: SourceConfig["families"] = {};
    for (const fam of FAMILY_ORDER) {
      families[fam] = defaultFamilyConfig(fam);
    }
    setConfig({ families, wire_defaults: "all_enabled_except_auth_required" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fetch the live Wire catalog once.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setCatalogStatus("loading");
      try {
        const result = await api.wireCatalog();
        if (cancelled) return;
        setCatalog(result.items);
        setCatalogStatus("ok");
        // First fetch: pre-check every non-auth-required platform across
        // categorised families. Idempotent thereafter — we only fill in
        // empty slug arrays so editing doesn't snap back.
        setConfig(seedWireSlugs(config, result.items));
      } catch (err) {
        if (cancelled) return;
        setCatalogStatus("error");
        setCatalogError(
          err instanceof ApiError
            ? `Couldn’t load Wire catalog: ${err.message}`
            : `Couldn’t load Wire catalog: ${(err as Error).message}`,
        );
      }
    }
    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const familyByCategory = useMemo(() => {
    const groups: Record<string, WireCatalogItem[]> = {};
    for (const item of catalog) {
      const cat = item.category || "other";
      groups[cat] = groups[cat] || [];
      groups[cat].push(item);
    }
    return groups;
  }, [catalog]);

  const updateFamily = (
    fam: FamilyKey,
    patch: Partial<FamilyConfig>,
  ) => {
    const current = config.families[fam] || defaultFamilyConfig(fam);
    setConfig({
      ...config,
      families: {
        ...config.families,
        [fam]: { ...current, ...patch },
      },
    });
  };

  const toggleSlug = (fam: FamilyKey, slug: string) => {
    const current = config.families[fam] || defaultFamilyConfig(fam);
    const cur = new Set(current.wire_platform_slugs || []);
    if (cur.has(slug)) cur.delete(slug);
    else cur.add(slug);
    updateFamily(fam, { wire_platform_slugs: Array.from(cur) });
  };

  return (
    <section className="space-y-6">
      <header>
        <h2 className="text-xl font-semibold text-ink-50">2. Where to listen</h2>
        <p className="mt-1 text-sm text-ink-300">
          Each family is on by default. Toggle off to skip, or expand to pick
          specific Wire platforms.
        </p>
      </header>

      {catalogStatus === "loading" && (
        <p className="text-xs text-ink-400">Loading Wire catalog from backend…</p>
      )}
      {catalogStatus === "error" && (
        <p className="text-xs text-rose-300">
          {catalogError}{" "}
          <button
            type="button"
            onClick={() => location.reload()}
            className="underline underline-offset-2"
          >
            retry
          </button>
        </p>
      )}

      <div className="space-y-3">
        {FAMILY_ORDER.map((fam) => {
          const meta = FAMILY_LABELS[fam];
          const cfg = config.families[fam] ?? defaultFamilyConfig(fam);
          const platforms = collectPlatforms(fam, familyByCategory);
          return (
            <FamilyCard
              key={fam}
              fam={fam}
              title={meta.title}
              blurb={meta.blurb}
              cfg={cfg}
              platforms={platforms}
              onToggleEnabled={(v) => updateFamily(fam, { enabled: v })}
              onToggleSlug={(slug) => toggleSlug(fam, slug)}
              onUrlsChange={(text) =>
                updateFamily(fam, {
                  urls: text
                    .split(/\r?\n/)
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              onMaxRunsChange={(v) =>
                updateFamily(fam, { max_runs_per_day: v })
              }
            />
          );
        })}
      </div>

      {submitError && (
        <p className="rounded-md border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-xs text-rose-300">
          {submitError}
        </p>
      )}

      <footer className="flex items-center justify-between pt-2">
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-ink-300 hover:text-ink-100"
        >
          ← Back
        </button>
        <button
          type="button"
          disabled={submitting}
          onClick={onSubmit}
          className={[
            "rounded-md px-4 py-2 text-sm font-medium transition",
            submitting
              ? "cursor-wait bg-ink-700 text-ink-400"
              : "bg-emerald-500 text-ink-900 hover:bg-emerald-400",
          ].join(" ")}
        >
          {submitting ? "Saving…" : "Save & finish"}
        </button>
      </footer>
    </section>
  );
}

// ---------- helpers ------------------------------------------------------

function defaultFamilyConfig(fam: FamilyKey): FamilyConfig {
  if (fam === "structured_intel")
    return { enabled: true, sources: ["osv", "nvd"] };
  if (fam === "agentic_search")
    return { enabled: true, max_runs_per_day: 4 };
  if (fam === "high_value_urls") return { enabled: true, urls: [] };
  return { enabled: true, wire_platform_slugs: [] };
}

function seedWireSlugs(cfg: SourceConfig, items: WireCatalogItem[]): SourceConfig {
  const families = { ...cfg.families };
  for (const fam of FAMILY_ORDER) {
    const cats = FAMILY_CATEGORIES[fam];
    if (!cats) continue;
    const current = families[fam] || defaultFamilyConfig(fam);
    if (current.wire_platform_slugs && current.wire_platform_slugs.length > 0) {
      continue; // user already touched it; leave alone
    }
    const matching = items
      .filter(
        (it) =>
          !it.auth_required &&
          it.category &&
          cats.includes(it.category.toLowerCase()),
      )
      .map((it) => it.slug);
    families[fam] = {
      ...current,
      wire_platform_slugs: matching,
    };
  }
  return { ...cfg, families };
}

function collectPlatforms(
  fam: FamilyKey,
  groups: Record<string, WireCatalogItem[]>,
): WireCatalogItem[] {
  const cats = FAMILY_CATEGORIES[fam];
  if (!cats) return [];
  const out: WireCatalogItem[] = [];
  for (const cat of cats) {
    out.push(...(groups[cat] || []));
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}

interface FamilyCardProps {
  fam: FamilyKey;
  title: string;
  blurb: string;
  cfg: FamilyConfig;
  platforms: WireCatalogItem[];
  onToggleEnabled: (v: boolean) => void;
  onToggleSlug: (slug: string) => void;
  onUrlsChange: (text: string) => void;
  onMaxRunsChange: (v: number) => void;
}

function FamilyCard({
  fam,
  title,
  blurb,
  cfg,
  platforms,
  onToggleEnabled,
  onToggleSlug,
  onUrlsChange,
  onMaxRunsChange,
}: FamilyCardProps) {
  const [open, setOpen] = useState<boolean>(false);
  const hasDetail =
    fam === "high_value_urls" ||
    fam === "agentic_search" ||
    platforms.length > 0;
  return (
    <div
      className={[
        "rounded-lg border bg-ink-800/30 transition",
        cfg.enabled
          ? "border-ink-700 hover:border-ink-600"
          : "border-ink-800 opacity-70",
      ].join(" ")}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <Toggle checked={cfg.enabled} onChange={onToggleEnabled} ariaLabel={title} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-ink-100">{title}</h3>
            {fam !== "structured_intel" && (
              <span className="text-[10px] uppercase tracking-wide text-ink-500">
                {fam.replace("_", " ")}
              </span>
            )}
          </div>
          <p className="text-xs text-ink-400">{blurb}</p>
        </div>
        {hasDetail && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-xs text-ink-300 hover:text-ink-100"
            disabled={!cfg.enabled}
          >
            {open ? "hide" : "edit"}
          </button>
        )}
      </div>

      {open && cfg.enabled && (
        <div className="border-t border-ink-800/80 px-4 py-3 text-sm">
          {fam === "high_value_urls" && (
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-400">
                Custom URLs (one per line)
              </span>
              <textarea
                value={(cfg.urls || []).join("\n")}
                onChange={(e) => onUrlsChange(e.target.value)}
                rows={3}
                placeholder="https://github.com/your-org/your-repo/security/advisories"
                className="w-full rounded border border-ink-700 bg-ink-900 px-2 py-1 font-mono text-xs text-ink-100 placeholder-ink-500 outline-none focus:border-emerald-500"
              />
            </label>
          )}
          {fam === "agentic_search" && (
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-400">
                Max runs per day
              </span>
              <input
                type="number"
                min={0}
                max={24}
                value={cfg.max_runs_per_day ?? 4}
                onChange={(e) =>
                  onMaxRunsChange(Math.max(0, Number(e.target.value) || 0))
                }
                className="w-24 rounded border border-ink-700 bg-ink-900 px-2 py-1 text-xs text-ink-100 outline-none focus:border-emerald-500"
              />
              <span className="ml-3 text-xs text-ink-400">
                Hard cap; pipeline backs off automatically.
              </span>
            </label>
          )}
          {platforms.length > 0 && (
            <div className="space-y-1">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-400">
                Wire platforms ({platforms.length})
              </span>
              <div className="grid grid-cols-2 gap-1.5">
                {platforms.map((p) => {
                  const checked = (cfg.wire_platform_slugs || []).includes(p.slug);
                  const disabled = p.auth_required;
                  return (
                    <label
                      key={p.slug}
                      className={[
                        "flex items-center gap-2 rounded border px-2 py-1 text-xs",
                        disabled
                          ? "cursor-not-allowed border-ink-800 bg-ink-900/40 text-ink-500"
                          : checked
                            ? "border-emerald-500/40 bg-emerald-500/5 text-ink-100"
                            : "border-ink-800 text-ink-300 hover:border-ink-700",
                      ].join(" ")}
                      title={
                        disabled
                          ? "Requires connecting a credential — V2."
                          : p.domain || ""
                      }
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => onToggleSlug(p.slug)}
                        className="accent-emerald-500"
                      />
                      <span className="truncate">{p.name}</span>
                      {disabled && (
                        <span className="ml-auto text-[10px] uppercase tracking-wide">
                          auth
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={() => onChange(!checked)}
      className={[
        "relative h-5 w-9 flex-none rounded-full border transition",
        checked
          ? "border-emerald-500 bg-emerald-500/30"
          : "border-ink-700 bg-ink-800",
      ].join(" ")}
    >
      <span
        className={[
          "absolute top-0.5 h-4 w-4 rounded-full transition",
          checked ? "left-[18px] bg-emerald-300" : "left-0.5 bg-ink-400",
        ].join(" ")}
      />
    </button>
  );
}
