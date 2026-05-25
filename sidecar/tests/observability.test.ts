/**
 * Tests for Sentry init + PII/PHI scrubbing (src/observability.ts).
 *
 * Lock in the load-bearing privacy guarantees: no options (no-op) without a DSN,
 * the lockdown flags + both scrub hooks when enabled, and that the scrubbers
 * strip the AI-prompt request body, identity, stack locals, and free-text PHI
 * before anything leaves the process. Mirrors apps/api/tests/test_observability.py.
 *
 * Secret-shaped fixtures are assembled at runtime so scanners don't flag literals.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import {
  scrubText,
  scrubErrorEvent,
  scrubTransactionEvent,
  sentryOptions,
} from "../src/observability.js";

const API_KEY = "sk-" + "A".repeat(24);
const GH_TOKEN = "ghp_" + "0".repeat(36);
const JWT = "eyJ" + "a".repeat(8) + "." + "b".repeat(8) + "." + "c".repeat(8);
const BEARER = "Bearer " + "token" + "1234567890";
const URL_PW = "examplepw" + "1234";
const FAKE_DSN = "https://" + "examplekey" + "@o0.ingest.sentry.invalid/0";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("sentryOptions", () => {
  it("returns null without a DSN (init is a no-op)", () => {
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_DSN", "");
    expect(sentryOptions()).toBeNull();
  });

  it("treats a whitespace-only DSN as unset", () => {
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_DSN", "   ");
    expect(sentryOptions()).toBeNull();
  });

  it("applies the privacy-lockdown options + both hooks when a DSN is set", () => {
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_DSN", FAKE_DSN);
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_ENVIRONMENT", "staging");
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_RELEASE", "abc1234");
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_TRACES_SAMPLE_RATE", "0");
    const opts = sentryOptions();
    expect(opts).not.toBeNull();
    expect(opts?.sendDefaultPii).toBe(false);
    expect(opts?.environment).toBe("staging");
    expect(opts?.release).toBe("abc1234");
    expect(opts?.tracesSampleRate).toBe(0);
    expect(typeof opts?.beforeSend).toBe("function");
    expect(typeof opts?.beforeSendTransaction).toBe("function");
  });

  it("treats an 'unknown' release (un-tagged build) as undefined", () => {
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_DSN", FAKE_DSN);
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_RELEASE", "unknown");
    expect(sentryOptions()?.release).toBeUndefined();
  });

  it("clamps an out-of-range traces sample rate", () => {
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_DSN", FAKE_DSN);
    vi.stubEnv("GLYCEMICGPT_SIDECAR_SENTRY_TRACES_SAMPLE_RATE", "5");
    expect(sentryOptions()?.tracesSampleRate).toBe(1);
  });
});

describe("scrubText", () => {
  it("redacts secrets and identifiers", () => {
    expect(scrubText("contact jane.doe@example.com")).toBe("contact [email]");
    expect(scrubText("key " + API_KEY)).toContain("[token]");
    expect(scrubText("key " + API_KEY)).not.toContain(API_KEY);
    expect(scrubText(GH_TOKEN)).toBe("[token]");
    expect(scrubText("auth " + JWT)).toContain("[jwt]");
    expect(scrubText("phone 15551234567")).toBe("phone [number]");
    expect(scrubText(BEARER)).toContain("bearer [token]");
  });

  it("redacts inline URL credentials", () => {
    const out = scrubText("conn https://user:" + URL_PW + "@db.host/path");
    expect(out).not.toContain(URL_PW);
    expect(out).toContain("[redacted]@");
  });

  it("keeps short numbers (glucose magnitudes) readable", () => {
    expect(scrubText("glucose reading 180 mg/dL")).toBe("glucose reading 180 mg/dL");
  });

  it("is bounded on large pathological input", () => {
    const pathological = "a.".repeat(8000) + "@" + "b".repeat(8000);
    const start = performance.now();
    const result = scrubText(pathological);
    expect(typeof result).toBe("string");
    expect(performance.now() - start).toBeLessThan(2000);
  });
});

describe("scrubErrorEvent", () => {
  it("strips the AI-prompt body, identity, stack locals, and free-text PHI", () => {
    const event = {
      server_name: "internal-host-01",
      user: { id: "u-1", email: "jane@example.com", username: "jane", ip_address: "1.2.3.4" },
      transaction: "/v1/u/123456789",
      exception: {
        values: [
          {
            value: "lookup failed for jane@example.com",
            stacktrace: { frames: [{ vars: { glucose: 350 } }] },
          },
        ],
      },
      threads: { values: [{ stacktrace: { frames: [{ vars: { s: "y" } }] } }] },
      message: "request from 15551234567 failed",
      request: {
        url: "https://user:" + URL_PW + "@host/v1/chat/completions?token=" + API_KEY,
        data: { messages: [{ role: "user", content: "my glucose is 350" }] },
        cookies: { session: "x" },
        headers: { authorization: "x" },
        env: { REMOTE_ADDR: "1.2.3.4" },
        query_string: "token=secret",
      },
      breadcrumbs: [{ message: "prompt from jane@example.com", data: { bg: 350 } }],
      extra: { raw_prompt: { content: "my glucose is 350" } },
    };

    scrubErrorEvent(event);

    expect("server_name" in event).toBe(false);
    expect(event.user).toEqual({ id: "u-1" });
    expect(event.transaction).not.toContain("123456789");
    expect("vars" in event.exception.values[0].stacktrace.frames[0]).toBe(false);
    expect(event.exception.values[0].value).not.toContain("@example.com");
    expect("vars" in event.threads.values[0].stacktrace.frames[0]).toBe(false);
    expect(event.message).not.toContain("15551234567");

    expect("data" in event.request).toBe(false); // AI prompt body dropped
    expect("cookies" in event.request).toBe(false);
    expect("headers" in event.request).toBe(false);
    expect("env" in event.request).toBe(false);
    expect(event.request.query_string).toBe("");
    expect(event.request.url).not.toContain(URL_PW);
    expect(event.request.url).not.toContain(API_KEY);
    expect(event.request.url).not.toContain("?");
    expect(event.request.url).toContain("[redacted]@");

    expect("breadcrumbs" in event).toBe(false); // breadcrumbs dropped wholesale
    expect("extra" in event).toBe(false);
  });

  it("scrubs tags carrying identifiers", () => {
    const event = { tags: { endpoint: "ok", actor_email: "jane@example.com" } };
    scrubErrorEvent(event);
    expect(event.tags.endpoint).toBe("ok");
    expect(event.tags.actor_email).not.toContain("@example.com");
  });
});

describe("scrubTransactionEvent", () => {
  it("scrubs spans (description/data/tags) and common fields", () => {
    const event = {
      transaction: "/v1/u/123456789",
      server_name: "internal-host-01",
      spans: [
        {
          description: "POST /v1/chat for jane@example.com",
          data: { prompt: "glucose 350" },
          tags: { who: "jane@example.com" },
        },
      ],
      request: {
        url: "https://user:" + URL_PW + "@host/v1?token=x",
        query_string: "token=x",
        headers: { x: "y" },
      },
    };

    scrubTransactionEvent(event);

    expect(event.spans[0].description).not.toContain("@example.com");
    expect("data" in event.spans[0]).toBe(false); // span data (prompt fragments) dropped
    expect(event.spans[0].tags.who).not.toContain("@example.com");
    expect("server_name" in event).toBe(false);
    expect(event.transaction).not.toContain("123456789");
    expect(event.request.query_string).toBe("");
    expect("headers" in event.request).toBe(false);
    expect(event.request.url).toContain("[redacted]@");
  });
});
