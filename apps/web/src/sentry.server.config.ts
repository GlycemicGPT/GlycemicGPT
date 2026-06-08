/**
 * Sentry init for the web app's SERVER (Node.js) runtime. Imported by
 * instrumentation.ts in the nodejs runtime only. No-op unless
 * GLYCEMICGPT_WEB_SENTRY_DSN is set.
 *
 * There is deliberately NO client (browser) or edge config: the browser ships
 * zero Sentry code and no DSN, so no Session Replay is possible by construction.
 * See PRIVACY.md and docs/concepts/privacy.md.
 */
import * as Sentry from "@sentry/nextjs";

import {
  readSentryEnv,
  scrubErrorEvent,
  scrubTransactionEvent,
  type MutableEvent,
} from "./lib/sentry-scrub";

const env = readSentryEnv();

if (env) {
  Sentry.init({
    dsn: env.dsn,
    environment: env.environment,
    release: env.release,
    // --- PII / data lockdown (see PRIVACY.md) ---
    sendDefaultPii: false,
    tracesSampleRate: env.tracesSampleRate, // tracing off by default
    beforeSend: (event) => {
      scrubErrorEvent(event as unknown as MutableEvent);
      return event;
    },
    beforeSendTransaction: (event) => {
      scrubTransactionEvent(event as unknown as MutableEvent);
      return event;
    },
    // Drop all breadcrumbs (console output / outbound fetch could carry user data).
    beforeBreadcrumb: () => null,
  });
}
