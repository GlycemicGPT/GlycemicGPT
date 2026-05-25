/**
 * Sentry PII/PHI scrubbing for the web SERVER runtime, plus the env reader.
 *
 * Sentry on the web is SERVER-SIDE ONLY: there is no browser/client init and no
 * `NEXT_PUBLIC_*` DSN, so nothing Sentry-related is shipped to the browser. The
 * DSN comes from the server-only `GLYCEMICGPT_WEB_SENTRY_DSN` env var and is a
 * no-op when unset. See PRIVACY.md and docs/concepts/privacy.md.
 *
 * This module is intentionally framework/SDK-free (pure functions) so it can be
 * unit-tested without loading the Sentry SDK; `sentry.server.config.ts` wires
 * these into `Sentry.init`. Mirrors apps/api/src/observability.py and
 * sidecar/src/observability.ts (a shared package is a future refactor).
 */

const SCRUB_PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/:\/\/[^/@\s]+@/g, "://[redacted]@"], // inline url credentials
  [/\b[\w.+-]{1,64}@[\w-]{1,255}\.[\w.-]{1,255}\b/g, "[email]"],
  [/\beyJ[\w-]+\.[\w-]+\.[\w-]+\b/g, "[jwt]"], // JWTs
  [/\bbearer\s+[A-Za-z0-9._-]{8,}/gi, "bearer [token]"],
  [/\b(?:sk|pk|rk)-[A-Za-z0-9]{16,}\b/g, "[token]"], // api keys
  [/\bgh[pousr]_[A-Za-z0-9]{20,}\b/g, "[token]"], // github tokens
  [/\bAKIA[0-9A-Z]{16}\b/g, "[token]"], // aws access key id
  [/\bxox[baprs]-[A-Za-z0-9-]{10,}\b/g, "[token]"], // slack tokens
  [/\b[A-Fa-f0-9]{32,}\b/g, "[hex]"], // long hex blobs / hashes
  [/\b[A-Za-z0-9+/]{40,}={0,2}\b/g, "[blob]"], // long base64-ish
  [/\b\d{9,}\b/g, "[number]"], // phone / device / record ids
];

// Clamp free text before regex scrubbing; the dropped tail is never sent.
const MAX_SCRUB_LEN = 8192;

const REQUEST_DROP_FIELDS = ["data", "cookies", "headers", "env"] as const;
const USER_DROP_FIELDS = ["email", "username", "ip_address", "name"] as const;

interface Stacktrace {
  frames?: Array<{ vars?: unknown }>;
}

/** Minimal structural view of the Sentry event fields we mutate in place. */
export interface MutableEvent {
  message?: string | { formatted?: string; message?: string };
  logentry?: { formatted?: string; message?: string };
  exception?: { values?: Array<{ value?: string; stacktrace?: Stacktrace }> };
  threads?: { values?: Array<{ stacktrace?: Stacktrace }> };
  user?: Record<string, unknown>;
  tags?: Record<string, unknown>;
  transaction?: string;
  culprit?: string;
  breadcrumbs?: unknown;
  request?: {
    url?: string;
    query_string?: unknown;
    data?: unknown;
    cookies?: unknown;
    headers?: unknown;
    env?: unknown;
  };
  extra?: unknown;
  server_name?: string;
  spans?: Array<{ description?: string; data?: unknown; tags?: Record<string, unknown> }>;
}

export function scrubText(text: string): string {
  let t = text.length > MAX_SCRUB_LEN ? text.slice(0, MAX_SCRUB_LEN) : text;
  for (const [pattern, replacement] of SCRUB_PATTERNS) {
    t = t.replace(pattern, replacement);
  }
  return t;
}

function dropFrameVars(stacktrace: Stacktrace | undefined): void {
  if (!stacktrace?.frames) return;
  for (const frame of stacktrace.frames) {
    if (frame && typeof frame === "object") delete frame.vars;
  }
}

function scrubLogentry(entry: { formatted?: string; message?: string }): void {
  if (typeof entry.formatted === "string") entry.formatted = scrubText(entry.formatted);
  if (typeof entry.message === "string") entry.message = scrubText(entry.message);
}

/** Scrub fields shared by error and transaction events (in place). */
function scrubCommon(event: MutableEvent): void {
  delete event.server_name;
  delete event.extra;

  if (event.user && typeof event.user === "object") {
    for (const field of USER_DROP_FIELDS) delete event.user[field];
  }

  if (event.tags && typeof event.tags === "object") {
    for (const [key, value] of Object.entries(event.tags)) {
      if (typeof value === "string") event.tags[key] = scrubText(value);
    }
  }

  if (typeof event.transaction === "string") event.transaction = scrubText(event.transaction);
  if (typeof event.culprit === "string") event.culprit = scrubText(event.culprit);

  // Drop breadcrumbs wholesale: console output and outbound fetch breadcrumbs
  // can carry user data, and pattern-scrubbing free text is not reliable. (The
  // init also sets beforeBreadcrumb to drop them at the source.)
  delete event.breadcrumbs;

  const request = event.request;
  if (request && typeof request === "object") {
    for (const field of REQUEST_DROP_FIELDS) delete request[field];
    if ("query_string" in request) request.query_string = "";
    if (typeof request.url === "string") {
      request.url = scrubText(request.url.split("?", 1)[0].split("#", 1)[0]);
    }
  }
}

/** Scrub an error event in-process before it is sent to Sentry. */
export function scrubErrorEvent(event: MutableEvent): void {
  for (const exc of event.exception?.values ?? []) {
    dropFrameVars(exc.stacktrace);
    if (typeof exc.value === "string") exc.value = scrubText(exc.value);
  }
  for (const thread of event.threads?.values ?? []) dropFrameVars(thread.stacktrace);

  if (typeof event.message === "string") event.message = scrubText(event.message);
  else if (event.message && typeof event.message === "object") scrubLogentry(event.message);
  if (event.logentry) scrubLogentry(event.logentry);

  scrubCommon(event);
}

/** Scrub a transaction (tracing) event before it is sent to Sentry. */
export function scrubTransactionEvent(event: MutableEvent): void {
  for (const span of event.spans ?? []) {
    if (span && typeof span === "object") {
      if (typeof span.description === "string") span.description = scrubText(span.description);
      delete span.data;
      if (span.tags && typeof span.tags === "object") {
        for (const [key, value] of Object.entries(span.tags)) {
          if (typeof value === "string") span.tags[key] = scrubText(value);
        }
      }
    }
  }
  scrubCommon(event);
}

export interface SentryEnv {
  dsn: string;
  environment: string;
  release: string | undefined;
  tracesSampleRate: number;
}

function parseTracesSampleRate(raw: string | undefined): number {
  const value = Number.parseFloat((raw ?? "").trim());
  if (!Number.isFinite(value) || value < 0) return 0;
  return value > 1 ? 1 : value;
}

/**
 * Read the server-only Sentry env, or `null` when no DSN is set (so the SDK is
 * never initialized). NOTE: the var is deliberately NOT `NEXT_PUBLIC_*` so it is
 * never inlined into the client bundle.
 */
export function readSentryEnv(): SentryEnv | null {
  const dsn = (process.env.GLYCEMICGPT_WEB_SENTRY_DSN ?? "").trim();
  if (!dsn) return null;

  const rawRelease = (process.env.GLYCEMICGPT_WEB_SENTRY_RELEASE ?? "").trim();
  return {
    dsn,
    environment: (process.env.GLYCEMICGPT_WEB_SENTRY_ENVIRONMENT ?? "development").trim(),
    release: rawRelease === "" || rawRelease === "unknown" ? undefined : rawRelease,
    tracesSampleRate: parseTracesSampleRate(process.env.GLYCEMICGPT_WEB_SENTRY_TRACES_SAMPLE_RATE),
  };
}
