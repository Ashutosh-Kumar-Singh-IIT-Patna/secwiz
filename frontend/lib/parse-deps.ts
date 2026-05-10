// Best-effort dependency parser for the onboarding textarea.
//
// Accepts (in priority order):
//   1. A JSON manifest like ``package.json``  → npm
//   2. A ``requirements.txt`` / ``Pipfile``-ish list → pypi
//   3. A ``go.mod`` body                          → go
//   4. A ``Cargo.toml`` ``[dependencies]`` block  → cargo
//   5. Bare lines                                  → software (default)
//
// Output is deduped on (ecosystem, name) and stable in input order.

import type { Dependency, Ecosystem } from "./types";

export interface ParseResult {
  deps: Dependency[];
  detected: string;          // human-readable label of which path matched
  warnings: string[];
}

export function parseDeps(input: string): ParseResult {
  const text = input.trim();
  if (!text) return { deps: [], detected: "empty", warnings: [] };

  // 1. Try JSON manifest (package.json shape).
  if (text.startsWith("{")) {
    try {
      const json = JSON.parse(text);
      const got = parsePackageJson(json);
      if (got.deps.length) return got;
    } catch {
      // Fall through to line parsing.
    }
  }

  // 2. Try line-based heuristics.
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.split(/[#;]/, 1)[0]) // strip line comments
    .map((line) => line.trim())
    .filter(Boolean);

  // 3. Quick guess for go.mod / Cargo.toml based on shape.
  if (/^module\s+\S+/m.test(text) && /^require\s/m.test(text)) {
    return parseGoMod(lines);
  }
  if (/^\[dependencies\]/m.test(text)) {
    return parseCargoToml(lines);
  }

  // 4. Pip-style ``name==1.2.3`` / ``name>=1.0`` / bare lines.
  const result: Dependency[] = [];
  const warnings: string[] = [];
  for (const line of lines) {
    const dep = parsePipLine(line) ?? parseBareLine(line);
    if (dep) result.push(dep);
    else warnings.push(`Skipped unrecognised line: "${truncate(line, 60)}"`);
  }
  const detected =
    result.some((d) => d.ecosystem === "pypi")
      ? "pypi (requirements.txt-style)"
      : "freeform";
  return { deps: dedupe(result), detected, warnings };
}

// ---------- package.json --------------------------------------------------

function parsePackageJson(json: unknown): ParseResult {
  if (!json || typeof json !== "object") {
    return { deps: [], detected: "json (no deps found)", warnings: [] };
  }
  const out: Dependency[] = [];
  const sections = ["dependencies", "devDependencies", "peerDependencies", "optionalDependencies"];
  for (const section of sections) {
    const block = (json as Record<string, unknown>)[section];
    if (block && typeof block === "object") {
      for (const [name, version] of Object.entries(block as Record<string, unknown>)) {
        if (!name) continue;
        out.push({
          ecosystem: "npm",
          name,
          raw_input: `${name}${typeof version === "string" ? `@${version}` : ""}`,
          version_spec: typeof version === "string" ? version : undefined,
        });
      }
    }
  }
  return {
    deps: dedupe(out),
    detected: out.length ? "package.json (npm)" : "json (no deps found)",
    warnings: [],
  };
}

// ---------- pip-style ----------------------------------------------------

const PIP_LINE = /^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\s*\[[^\]]*\])?\s*([<>=!~]=?[^\s,]+(?:\s*,\s*[<>=!~]=?[^\s,]+)*)?/;

function parsePipLine(line: string): Dependency | null {
  // Skip pip flags and URL-style requirements — they don't carry a clean
  // package name we can match a watchlist on.
  if (line.startsWith("-") || line.includes("://")) return null;
  const match = line.match(PIP_LINE);
  if (!match) return null;
  const name = match[1];
  const version = match[2] || undefined;
  // pip names are case-insensitive but normalize to lowercase.
  const lowered = name.toLowerCase();
  // If the line had no version spec AND no ``==`` style hint, fall back
  // to ``software`` so we don't mislabel arbitrary "lodash" lines as pypi.
  const looksPypi = Boolean(version) || /^[a-z0-9._-]+$/.test(name);
  const ecosystem: Ecosystem = looksPypi && version ? "pypi" : "software";
  return {
    ecosystem,
    name: lowered,
    raw_input: line,
    version_spec: version,
  };
}

function parseBareLine(line: string): Dependency | null {
  // Allow ``ecosystem:name`` syntax for explicit tagging from the user.
  const tagged = line.match(/^([a-z]+):\s*(\S.+)$/i);
  if (tagged) {
    const ecosystem = normaliseEcosystem(tagged[1]);
    return {
      ecosystem,
      name: tagged[2].trim(),
      raw_input: line,
    };
  }
  if (!/^[\w@./+-]+$/.test(line)) return null;
  return {
    ecosystem: "software",
    name: line,
    raw_input: line,
  };
}

// ---------- go.mod -------------------------------------------------------

function parseGoMod(lines: string[]): ParseResult {
  const deps: Dependency[] = [];
  let inRequire = false;
  for (const line of lines) {
    if (line.startsWith("require (")) {
      inRequire = true;
      continue;
    }
    if (inRequire && line === ")") {
      inRequire = false;
      continue;
    }
    const stripped = inRequire ? line : line.replace(/^require\s+/, "");
    const match = stripped.match(/^(\S+)\s+(\S+)/);
    if (match && match[1].includes("/")) {
      deps.push({
        ecosystem: "go",
        name: match[1],
        raw_input: stripped,
        version_spec: match[2],
      });
    }
  }
  return { deps: dedupe(deps), detected: "go.mod", warnings: [] };
}

// ---------- Cargo.toml ---------------------------------------------------

function parseCargoToml(lines: string[]): ParseResult {
  const deps: Dependency[] = [];
  let inDeps = false;
  for (const line of lines) {
    if (/^\[dependencies\]/.test(line)) {
      inDeps = true;
      continue;
    }
    if (line.startsWith("[")) {
      inDeps = false;
      continue;
    }
    if (!inDeps) continue;
    const match = line.match(/^([A-Za-z0-9_-]+)\s*=\s*(.+)$/);
    if (match) {
      const versionMatch = match[2].match(/"([^"]+)"/);
      deps.push({
        ecosystem: "cargo",
        name: match[1],
        raw_input: line,
        version_spec: versionMatch?.[1],
      });
    }
  }
  return { deps: dedupe(deps), detected: "Cargo.toml", warnings: [] };
}

// ---------- helpers ------------------------------------------------------

function normaliseEcosystem(s: string): Ecosystem {
  const lc = s.toLowerCase();
  const known: Ecosystem[] = [
    "npm",
    "pypi",
    "go",
    "maven",
    "rubygems",
    "nuget",
    "cargo",
    "packagist",
    "composer",
    "software",
    "saas",
  ];
  return (known as string[]).includes(lc) ? (lc as Ecosystem) : "software";
}

function dedupe(deps: Dependency[]): Dependency[] {
  const seen = new Set<string>();
  const out: Dependency[] = [];
  for (const d of deps) {
    const key = `${d.ecosystem}:${d.name.toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(d);
  }
  return out;
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
