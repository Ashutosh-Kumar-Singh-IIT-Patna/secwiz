// Browser-facing API client. Hits the FastAPI backend directly except
// for the demo trigger, which goes through a Next.js API route so the
// X-Demo-Token header lives only on the server.

import type {
  OnboardRequest,
  OnboardResponse,
  TriggerResponse,
  WireCatalogResponse,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(init?.headers || {}),
      },
    });
  } catch (err) {
    throw new ApiError(0, null, `network error reaching ${url}: ${err}`);
  }

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    const detail =
      typeof body === "object" && body && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : response.statusText;
    throw new ApiError(response.status, body, `${response.status} ${detail}`);
  }
  return body as T;
}

export const api = {
  healthz: () => request<{ ok: boolean }>("/v1/healthz"),
  wireCatalog: (refresh = false) =>
    request<WireCatalogResponse>(`/v1/wire-catalog${refresh ? "?refresh=true" : ""}`),
  onboard: (payload: OnboardRequest) =>
    request<OnboardResponse>("/v1/onboard", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  // Trigger is intentionally NOT here — it goes through /api/trigger so
  // the demo token stays server-side. Use `triggerRun()` below.
};

export async function triggerRun(userId: string): Promise<TriggerResponse> {
  const response = await fetch("/api/trigger", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId }),
  });
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    const detail =
      typeof body === "object" && body && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : response.statusText;
    throw new ApiError(response.status, body, `${response.status} ${detail}`);
  }
  return body as TriggerResponse;
}

export { ApiError };
