/**
 * Next.js instrumentation hook. Initializes Sentry on the SERVER (Node.js)
 * runtime only and forwards server request errors. There is no browser/client
 * or edge init -- the client bundle ships no Sentry code. No-op unless
 * GLYCEMICGPT_WEB_SENTRY_DSN is set. See PRIVACY.md.
 *
 * Deliberate scope deferrals (keep this PR server-only + dependency-light):
 *   1. Edge-runtime (middleware) errors are NOT captured -- nodejs only.
 *   2. No withSentryConfig, so server stack traces are not source-mapped
 *      (that needs a build-time auth token). Error capture still works via
 *      onRequestError + the nodejs init below.
 */
import * as Sentry from "@sentry/nextjs";

export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
}

// Next.js calls this on server request errors; captureRequestError routes them
// through Sentry's beforeSend scrubbers (and is a no-op when Sentry is disabled).
export const onRequestError = Sentry.captureRequestError;
