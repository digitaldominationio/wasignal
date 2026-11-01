import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API_BASE = (process.env.API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

async function forward(request: NextRequest, path: string[]) {
  const url = `${API_BASE}/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const [key, value] of request.headers.entries()) {
    // let fetch set its own host/length; cookies must pass through untouched
    if (["host", "connection", "content-length", "accept-encoding"].includes(key)) continue;
    headers.set(key, value);
  }

  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(url, { method, headers, body, redirect: "manual", cache: "no-store" });
  } catch {
    return Response.json({ detail: "api_unreachable" }, { status: 502 });
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    // content-encoding/length describe the upstream body, not this response
    if (["content-encoding", "content-length", "transfer-encoding", "connection"].includes(key)) return;
    responseHeaders.set(key, value);
  });

  const payload = await upstream.arrayBuffer();
  return new Response(payload, { status: upstream.status, headers: responseHeaders });
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}
export async function POST(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}
export async function PUT(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}
export async function PATCH(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}
export async function DELETE(request: NextRequest, context: Context) {
  return forward(request, (await context.params).path);
}
