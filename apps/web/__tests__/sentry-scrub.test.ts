/**
 * Tests for the web server's Sentry scrubbers + env reader (src/lib/sentry-scrub.ts).
 *
 * The module is framework-free (no Sentry SDK), so these run as plain unit tests.
 * Secret-shaped fixtures are assembled at runtime so scanners don't flag literals.
 */
import {
  scrubText,
  scrubErrorEvent,
  scrubTransactionEvent,
  readSentryEnv,
  type MutableEvent,
} from "@/lib/sentry-scrub";

describe("readSentryEnv", () => {
  const ORIG = process.env;
  beforeEach(() => {
    process.env = { ...ORIG };
  });
  afterEach(() => {
    process.env = ORIG;
  });

  it("returns null without a DSN (init is a no-op)", () => {
    delete process.env.GLYCEMICGPT_WEB_SENTRY_DSN;
    expect(readSentryEnv()).toBeNull();
  });

  it("treats a whitespace-only DSN as unset", () => {
    process.env.GLYCEMICGPT_WEB_SENTRY_DSN = "   ";
    expect(readSentryEnv()).toBeNull();
  });

  it("reads config when set; 'unknown' release -> undefined; clamps sample rate", () => {
    process.env.GLYCEMICGPT_WEB_SENTRY_DSN =
      "https://" + "examplekey" + "@o0.ingest.sentry.invalid/0";
    process.env.GLYCEMICGPT_WEB_SENTRY_ENVIRONMENT = "staging";
    process.env.GLYCEMICGPT_WEB_SENTRY_RELEASE = "unknown";
    process.env.GLYCEMICGPT_WEB_SENTRY_TRACES_SAMPLE_RATE = "5";
    const env = readSentryEnv();
    expect(env).not.toBeNull();
    expect(env?.environment).toBe("staging");
    expect(env?.release).toBeUndefined();
    expect(env?.tracesSampleRate).toBe(1);
  });
});

describe("scrubText", () => {
  const API_KEY = "sk-" + "A".repeat(24);
  const GH = "ghp_" + "0".repeat(36);

  it("redacts secrets/identifiers and keeps short numbers readable", () => {
    expect(scrubText("contact jane.doe@example.com")).toBe("contact [email]");
    expect(scrubText("key " + API_KEY)).not.toContain(API_KEY);
    expect(scrubText(GH)).toBe("[token]");
    expect(scrubText("phone 15551234567")).toBe("phone [number]");
    expect(scrubText("glucose 180 mg/dL")).toBe("glucose 180 mg/dL");
  });

  it("clamps oversized input and stays fast (ReDoS guard)", () => {
    const tail = "ZZTAILZZ";
    const input = "a.".repeat(8000) + tail; // tail is past the 8192 clamp
    const start = performance.now();
    const out = scrubText(input);
    expect(performance.now() - start).toBeLessThan(200);
    expect(out).not.toContain(tail);
  });
});

describe("scrubErrorEvent", () => {
  it("drops request body/identity/breadcrumbs/locals and scrubs free text", () => {
    const event: MutableEvent = {
      server_name: "host-1",
      user: { id: "u-1", email: "jane@example.com", ip_address: "1.2.3.4" },
      message: "failed for jane@example.com phone 15551234567",
      exception: {
        values: [
          {
            value: "boom for jane@example.com",
            stacktrace: { frames: [{ vars: { secret: "x" } }] },
          },
        ],
      },
      request: {
        url: "https://user:pw1234@host/dashboard?token=secret123",
        data: { glucose: 350 },
        cookies: { s: "x" },
        headers: { authorization: "x" },
        env: { X: "y" },
        query_string: "token=abc",
      },
      breadcrumbs: [{ message: "loaded jane@example.com" }],
      extra: { raw: { glucose: 350 } },
    };

    scrubErrorEvent(event);

    expect("server_name" in event).toBe(false);
    expect(event.user).toEqual({ id: "u-1" });
    expect(event.message).not.toContain("@example.com");
    expect(event.message).not.toContain("15551234567");
    expect("vars" in event.exception!.values![0].stacktrace!.frames![0]).toBe(false);
    expect("data" in event.request!).toBe(false); // request body dropped
    expect("cookies" in event.request!).toBe(false);
    expect("headers" in event.request!).toBe(false);
    expect(event.request!.query_string).toBe("");
    expect(event.request!.url).not.toContain("?");
    expect(event.request!.url).toContain("[redacted]@");
    expect("breadcrumbs" in event).toBe(false); // dropped wholesale
    expect("extra" in event).toBe(false);
  });
});

describe("scrubTransactionEvent", () => {
  it("scrubs spans (description/data/tags) and common fields", () => {
    const event: MutableEvent = {
      transaction: "/u/123456789",
      spans: [
        {
          description: "GET for jane@example.com",
          data: { q: "x" },
          tags: { who: "jane@example.com" },
        },
      ],
    };

    scrubTransactionEvent(event);

    expect(event.transaction).not.toContain("123456789");
    expect(event.spans![0].description).not.toContain("@example.com");
    expect("data" in event.spans![0]).toBe(false);
    expect(event.spans![0].tags!.who).not.toContain("@example.com");
  });
});
