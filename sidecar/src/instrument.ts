/**
 * Sentry bootstrap. Imported first (before express/http) so the SDK can set up
 * instrumentation before those modules load. No-op unless a DSN is configured.
 *
 * Error capture works with this top-of-entry import. If performance TRACING is
 * ever enabled (tracesSampleRate > 0), switch the start command to
 * `node --import ./dist/instrument.js dist/server.js` so OpenTelemetry can
 * instrument the ESM http/express modules. See observability.ts.
 */
import { initSentry } from "./observability.js";

initSentry();
