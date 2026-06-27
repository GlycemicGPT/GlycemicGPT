/**
 * Unit tests for the Anthropic API-key vision provider.
 *
 * `fetch` is mocked — no network calls. The provider uses ONLY an Anthropic API
 * key (x-api-key); it must never send a subscription OAuth Bearer token or the
 * Claude Code preamble.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AnthropicVisionProvider } from "../src/providers/anthropic-vision.js";
import {
  InvalidImageError,
  VisionUnavailableError,
} from "../src/providers/image-utils.js";
import type { MultimodalMessage } from "../src/providers/types.js";

const PNG_1x1 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWqM7HQAAAABJRU5ErkJggg==";
const PNG_DATA_URL = `data:image/png;base64,${PNG_1x1}`;

function imageMessage(text: string): MultimodalMessage[] {
  return [
    {
      role: "user",
      content: [
        { type: "image_url", image_url: { url: PNG_DATA_URL } },
        { type: "text", text },
      ],
    },
  ];
}

function okFetch(text = "blue") {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      type: "message",
      model: "claude-sonnet-4-5-20250929",
      content: [{ type: "text", text }],
    }),
  });
}

describe("AnthropicVisionProvider", () => {
  let provider: AnthropicVisionProvider;

  beforeEach(() => {
    provider = new AnthropicVisionProvider();
    vi.stubEnv("ANTHROPIC_API_KEY", "");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  describe("supportsVision", () => {
    it("is false without an API key", () => {
      expect(provider.supportsVision()).toBe(false);
    });

    it("is true with an API key", () => {
      vi.stubEnv("ANTHROPIC_API_KEY", "sk-ant-test");
      expect(provider.supportsVision()).toBe(true);
    });

    it("throws VisionUnavailableError when not configured", async () => {
      await expect(provider.completeVision(imageMessage("hi"))).rejects.toBeInstanceOf(
        VisionUnavailableError,
      );
    });
  });

  describe("request construction (api_key only)", () => {
    beforeEach(() => {
      vi.stubEnv("ANTHROPIC_API_KEY", "sk-ant-test");
    });

    it("authenticates with x-api-key and never sends OAuth headers/preamble", async () => {
      const mockFetch = okFetch();
      vi.stubGlobal("fetch", mockFetch);

      await provider.completeVision([
        { role: "system", content: "Describe the food." },
        ...imageMessage("estimate"),
      ]);

      const [, init] = mockFetch.mock.calls[0];
      const headers = init.headers as Record<string, string>;
      expect(headers["x-api-key"]).toBe("sk-ant-test");
      expect(headers["authorization"]).toBeUndefined();
      expect(headers["anthropic-beta"]).toBeUndefined();

      const sent = JSON.parse(init.body as string);
      // System carries the caller's instruction only — no Claude Code preamble.
      expect(sent.system).toEqual([{ type: "text", text: "Describe the food." }]);
      const systemText = JSON.stringify(sent.system);
      expect(systemText).not.toContain("Claude Code");

      const imageBlock = sent.messages[0].content.find(
        (b: { type: string }) => b.type === "image",
      );
      expect(imageBlock.source).toEqual({
        type: "base64",
        media_type: "image/png",
        data: PNG_1x1,
      });
    });

    it("merges consecutive same-role messages into one alternating turn", async () => {
      const mockFetch = okFetch();
      vi.stubGlobal("fetch", mockFetch);
      await provider.completeVision([
        { role: "user", content: "first" },
        ...imageMessage("second"),
      ]);
      const sent = JSON.parse(mockFetch.mock.calls[0][1].body as string);
      // Both user turns collapse into a single user message (no non-alternating
      // sequence reaches the Anthropic API).
      expect(sent.messages).toHaveLength(1);
      expect(sent.messages[0].role).toBe("user");
      expect(sent.messages[0].content.some((b: { type: string }) => b.type === "image")).toBe(true);
    });

    it("resolves model aliases and defaults unknown models to sonnet", async () => {
      const mockFetch = okFetch();
      vi.stubGlobal("fetch", mockFetch);
      await provider.completeVision(imageMessage("x"), { model: "totally-unknown" });
      const sent = JSON.parse(mockFetch.mock.calls[0][1].body as string);
      expect(sent.model).toBe("claude-sonnet-4-5-20250929");
    });

    it("forwards max_tokens and parses the response", async () => {
      const mockFetch = okFetch("roughly 40-55 g of carbs");
      vi.stubGlobal("fetch", mockFetch);
      const result = await provider.completeVision(imageMessage("x"), { maxTokens: 333 });
      const sent = JSON.parse(mockFetch.mock.calls[0][1].body as string);
      expect(sent.max_tokens).toBe(333);
      expect(result.content).toBe("roughly 40-55 g of carbs");
    });

    it("rejects a remote image URL without fetching it", async () => {
      const mockFetch = okFetch();
      vi.stubGlobal("fetch", mockFetch);
      const messages: MultimodalMessage[] = [
        {
          role: "user",
          content: [{ type: "image_url", image_url: { url: "https://evil.example/x.png" } }],
        },
      ];
      await expect(provider.completeVision(messages)).rejects.toBeInstanceOf(InvalidImageError);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("retries on 429 then succeeds", async () => {
      const mockFetch = vi
        .fn()
        .mockResolvedValueOnce({ ok: false, status: 429, json: async () => ({}) })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ model: "claude-sonnet-4-5-20250929", content: [{ type: "text", text: "ok" }] }),
        });
      vi.stubGlobal("fetch", mockFetch);
      const result = await provider.completeVision(imageMessage("x"));
      expect(result.content).toBe("ok");
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it("surfaces a generic error without leaking the response body", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: false,
          status: 400,
          json: async () => ({ error: { message: "secret detail" } }),
        }),
      );
      await expect(provider.completeVision(imageMessage("x"))).rejects.toThrow(
        /Anthropic vision request failed \(HTTP 400\)/,
      );
      await expect(provider.completeVision(imageMessage("x"))).rejects.not.toThrow(/secret detail/);
    });
  });
});
