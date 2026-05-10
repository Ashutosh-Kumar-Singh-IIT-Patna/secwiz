import { NextResponse } from "next/server";

// Server-only proxy for ``POST /v1/runs/trigger``. Keeps the
// ``X-Demo-Token`` header off the browser bundle. The frontend posts
// here; this route forwards to the FastAPI backend with the secret
// header read from process.env.

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const backend = process.env.BACKEND_URL || "http://localhost:8000";
  const token = process.env.DEMO_TRIGGER_TOKEN || "";
  if (!token) {
    return NextResponse.json(
      { detail: "DEMO_TRIGGER_TOKEN not configured on the server" },
      { status: 500 },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "invalid json body" }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backend}/v1/runs/trigger`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Demo-Token": token,
      },
      body: JSON.stringify(body),
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `backend unreachable: ${(err as Error).message}` },
      { status: 502 },
    );
  }

  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
