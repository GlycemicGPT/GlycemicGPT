/**
 * SSE proxy route for the glucose stream.
 *
 * Next.js rewrites buffer streaming responses, which breaks Server-Sent
 * Events. This route handler explicitly streams the backend SSE response
 * to the browser using a ReadableStream, bypassing the rewrite proxy for
 * this specific endpoint.
 *
 * File-system API routes take priority over rewrites, so all other /api/*
 * requests continue to use the rewrite defined in next.config.ts.
 */

import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Timeout for the initial backend connection (30 seconds). */
const BACKEND_CONNECT_TIMEOUT_MS = 30_000;

export async function GET(request: NextRequest) {
  const apiUrl = process.env.API_URL || "http://localhost:8000";

  // Forward the session cookie to the backend for authentication
  const cookie = request.headers.get("cookie") || "";

  // Abort if the client disconnects OR the backend takes too long to respond
  const timeout = AbortSignal.timeout(BACKEND_CONNECT_TIMEOUT_MS);
  const signal = AbortSignal.any([request.signal, timeout]);

  let backendResponse: Response;
  try {
    backendResponse = await fetch(`${apiUrl}/api/v1/glucose/stream`, {
      headers: {
        cookie,
        accept: "text/event-stream",
      },
      signal,
    });
  } catch (err: unknown) {
    const isAbort =
      err instanceof DOMException && err.name === "AbortError";
    const message = isAbort
      ? "Client disconnected or connection timed out"
      : "Backend connection failed";
    // 499 (client closed) for aborts, 502 for everything else
    return new Response(message, { status: isAbort ? 499 : 502 });
  }

  if (!backendResponse.ok) {
    const body = await backendResponse.text().catch(() => backendResponse.statusText);
    return new Response(body, {
      status: backendResponse.status,
      headers: { "content-type": "text/plain" },
    });
  }

  if (!backendResponse.body) {
    return new Response("No stream body", { status: 502 });
  }

  // Stream the backend SSE response directly to the client.
  // x-accel-buffering: no disables buffering in Nginx reverse proxies.
  return new Response(backendResponse.body, {
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
    },
  });
}
