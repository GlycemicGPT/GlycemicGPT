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

  // The timeout must bound only the INITIAL connection, not the whole stream.
  // SSE responses stay open indefinitely, so leaving a timeout armed on the
  // fetch signal would abort a healthy stream ~30s in -- killing the glucose
  // feed and surfacing the abort as a TimeoutError in Next's response pipe.
  // Use a dedicated controller cleared as soon as the backend responds; the
  // client-disconnect signal stays attached so navigating away still tears
  // down the upstream fetch.
  // Abort the connect with a TimeoutError reason (distinct from the AbortError
  // a client disconnect raises on request.signal) so the two are told apart.
  const connectController = new AbortController();
  const connectTimer = setTimeout(
    () =>
      connectController.abort(
        new DOMException("Backend connection timed out", "TimeoutError")
      ),
    BACKEND_CONNECT_TIMEOUT_MS
  );
  const signal = AbortSignal.any([request.signal, connectController.signal]);

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
    // A slow/hung backend hits the connect timeout (504); the client navigating
    // away aborts request.signal (499); anything else is a real failure (502).
    if (err instanceof DOMException && err.name === "TimeoutError") {
      return new Response("Backend connection timed out", { status: 504 });
    }
    if (err instanceof DOMException && err.name === "AbortError") {
      return new Response("Client disconnected", { status: 499 });
    }
    return new Response("Backend connection failed", { status: 502 });
  } finally {
    // Stop the connect timeout so it can never fire mid-stream.
    clearTimeout(connectTimer);
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

  // Pipe the backend SSE through a wrapper instead of returning its body
  // directly. When the client navigates away, request.signal aborts the
  // upstream fetch, which surfaces as an undici SocketError on the in-flight
  // body -- returning the body directly lets that error escape into Next's
  // response pipe and reach Sentry. Reading it ourselves lets us treat a
  // client-disconnect abort as a normal end-of-stream and close cleanly.
  const upstream = backendResponse.body.getReader();
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      try {
        const { done, value } = await upstream.read();
        if (done) {
          controller.close();
          return;
        }
        controller.enqueue(value);
      } catch {
        // Upstream aborted (client gone) or dropped -- expected teardown, not
        // an error worth reporting. Close gracefully.
        try {
          controller.close();
        } catch {
          /* already closing/cancelled */
        }
      }
    },
    async cancel(reason) {
      // Client went away: tear down the upstream fetch so the backend
      // connection isn't leaked. The cancel itself may reject as the socket
      // aborts -- that's expected.
      try {
        await upstream.cancel(reason);
      } catch {
        /* ignore */
      }
    },
  });

  // x-accel-buffering: no disables buffering in Nginx reverse proxies.
  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      "x-accel-buffering": "no",
    },
  });
}
