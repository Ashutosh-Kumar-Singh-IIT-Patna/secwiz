// Shapes that mirror the FastAPI backend's request/response models. Kept
// hand-typed (rather than auto-gen'd from OpenAPI) for V1 simplicity —
// the surface is small and stable.

export type Ecosystem =
  | "npm"
  | "pypi"
  | "go"
  | "maven"
  | "rubygems"
  | "nuget"
  | "cargo"
  | "packagist"
  | "composer"
  | "software"
  | "saas";

export const KNOWN_ECOSYSTEMS: Ecosystem[] = [
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

export interface Dependency {
  ecosystem: Ecosystem;
  name: string;
  raw_input?: string;
  aliases?: string[];
  version_spec?: string;
}

export type FamilyKey =
  | "social_media"
  | "news"
  | "blogs"
  | "high_value_urls"
  | "agentic_search"
  | "structured_intel";

export const FAMILY_LABELS: Record<FamilyKey, { title: string; blurb: string }> = {
  structured_intel: {
    title: "Structured advisories",
    blurb: "OSV.dev + NVD — authoritative CVE / advisory feeds.",
  },
  news: {
    title: "News",
    blurb: "Reuters, TechCrunch, Hacker News & friends via Wire.",
  },
  blogs: {
    title: "Blogs",
    blurb: "Medium, Substack, Dev.to via Wire.",
  },
  social_media: {
    title: "Social media",
    blurb: "Reddit, YouTube and other public signal via Wire.",
  },
  high_value_urls: {
    title: "Custom URLs",
    blurb: "Pin specific advisory pages or release notes you trust.",
  },
  agentic_search: {
    title: "Agentic search (LLM-powered)",
    blurb: "Bounded research prompts. Off-budget calls per day are capped.",
  },
};

export interface FamilyConfig {
  enabled: boolean;
  wire_platform_slugs?: string[];
  urls?: string[];
  sources?: string[];
  max_runs_per_day?: number;
}

export interface SourceConfig {
  families: Partial<Record<FamilyKey, FamilyConfig>>;
  wire_defaults?: "all_enabled_except_auth_required" | "none" | "manual";
}

export interface OnboardRequest {
  email: string;
  dependencies: Dependency[];
  source_config: SourceConfig;
}

export interface OnboardResponse {
  ok: boolean;
  user_id: string;
  watch_item_count: number;
}

export interface WireCatalogItem {
  slug: string;
  name: string;
  domain?: string | null;
  category?: string | null;
  auth_required: boolean;
}

export interface WireCatalogResponse {
  items: WireCatalogItem[];
  fetched_at: string;
  cached: boolean;
}

export interface TriggerResponse {
  ok: boolean;
  run: {
    id: string;
    user_id: string;
    started_at: string;
    finished_at: string;
    stats: {
      docs?: number;
      candidates?: number;
      events?: number;
      alerts_sent?: number;
      llm_suppressed?: number;
    };
    error: string | null;
  };
}
