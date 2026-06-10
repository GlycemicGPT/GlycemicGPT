/**
 * Sentry error monitoring for the AI sidecar: init + PII/PHI scrubbing.
 *
 * Sentry is OFF unless `GLYCEMICGPT_SIDECAR_SENTRY_DSN` is set. The DSN is
 * supplied only in the project's own dev/CI/staging via a runtime environment
 * variable and is never baked into a distributed build. A self-hoster may set
 * their own DSN to send errors to their own Sentry account. See PRIVACY.md and
 * docs/concepts/privacy.md.
 *
 * This service is the highest-PHI surface in the platform: request bodies are
 * AI prompts that can contain health data. The scrubbers below drop request
 * bodies, headers, cookies, stack-frame locals, the user identity, and the
 * `extra` dump, and pattern-scrub free text, before any event leaves the
 * process. Mirrors apps/api/src/observability.py.
 */

import * as Sentry from "@sentry/node";

// Best-effort, readability-preserving redaction of high-risk patterns that can
// appear in free text (exception messages, breadcrumbs, span descriptions,
// URLs). Length-bounded quantifiers + an input clamp keep this linear-time
// (defense against ReDoS-style input). Short numbers (e.g. glucose values) are
// intentionally left readable; the no-PHI-in-messages guideline and Sentry's
// server-side Advanced Data Scrubbing cover those.
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

// Request sub-fields that are never needed for triage and are the highest PHI
// risk (data = the AI prompt body); dropped wholesale before the event leaves.
const REQUEST_DROP_FIELDS = ["data", "cookies", "headers", "env"] as const;
// User identity fields dropped defensively; an opaque id is left.
const USER_DROP_FIELDS = ["email", "username", "ip_address", "name"] as const;

/** Minimal structural view of the Sentry event fields we mutate in place. */
interface Frame {
  vars?: unknown;
}
interface Stacktrace {
  frames?: Frame[];
}
interface MutableEvent {
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

  // Drop breadcrumbs wholesale. This service's console output and CLI-subprocess
  // stderr can carry prompt or health context, and pattern-scrubbing free text is
  // not reliable enough for the highest-PHI surface. (beforeBreadcrumb also stops
  // them being recorded at all; this is belt-and-suspenders.)
  delete event.breadcrumbs;

  const request = event.request;
  if (request && typeof request === "object") {
    for (const field of REQUEST_DROP_FIELDS) delete request[field];
    if ("query_string" in request) request.query_string = "";
    if (typeof request.url === "string") {
      // Strip query string and fragment (a token glued into them can survive
      // pattern-scrubbing); keep scheme/host/path and scrub that.
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
      delete span.data; // span data carries query params / SQL binds / prompt fragments
      if (span.tags && typeof span.tags === "object") {
        for (const [key, value] of Object.entries(span.tags)) {
          if (typeof value === "string") span.tags[key] = scrubText(value);
        }
      }
    }
  }
  scrubCommon(event);
}

type SentryInitOptions = NonNullable<Parameters<typeof Sentry.init>[0]>;

function parseTracesSampleRate(raw: string | undefined): number {
  const value = Number.parseFloat((raw ?? "").trim());
  if (!Number.isFinite(value) || value < 0) return 0;
  return value > 1 ? 1 : value;
}

/**
 * Build the Sentry init options, or `null` when no DSN is configured (so the
 * SDK is never initialized and the service sends nothing).
 */
export function sentryOptions(): SentryInitOptions | null {
  const dsn = (process.env.GLYCEMICGPT_SIDECAR_SENTRY_DSN ?? "").trim();
  if (!dsn) return null;

  const rawRelease = (process.env.GLYCEMICGPT_SIDECAR_SENTRY_RELEASE ?? "").trim();
  const release = rawRelease === "" || rawRelease === "unknown" ? undefined : rawRelease;

  return {
    dsn,
    environment: (process.env.GLYCEMICGPT_SIDECAR_SENTRY_ENVIRONMENT ?? "development").trim(),
    release,
    // --- PII / data lockdown (see PRIVACY.md) ---
    sendDefaultPii: false, // no request bodies/headers/cookies/IP auto-attached
    // tracing off by default (errors only); raise via env to sample
    tracesSampleRate: parseTracesSampleRate(
      process.env.GLYCEMICGPT_SIDECAR_SENTRY_TRACES_SAMPLE_RATE,
    ),
    beforeSend: (event) => {
      scrubErrorEvent(event as unknown as MutableEvent);
      return event;
    },
    beforeSendTransaction: (event) => {
      scrubTransactionEvent(event as unknown as MutableEvent);
      return event;
    },
    // Drop all breadcrumbs: for the highest-PHI service, console / CLI-stderr
    // breadcrumbs are not worth the leak risk (see scrubCommon).
    beforeBreadcrumb: () => null,
  };
}

let enabled = false;

/** Initialize Sentry if a DSN is configured; otherwise a no-op. */
export function initSentry(): void {
  const options = sentryOptions();
  if (!options) {
    console.log(
      JSON.stringify({ level: "info", msg: "Sentry disabled (GLYCEMICGPT_SIDECAR_SENTRY_DSN not set)" }),
    );
    return;
  }
  Sentry.init(options);
  enabled = true;
  console.log(
    JSON.stringify({
      level: "info",
      msg: "Sentry enabled",
      environment: options.environment,
      release: options.release ?? "unset",
    }),
  );
}

export function isSentryEnabled(): boolean {
  return enabled;
}
