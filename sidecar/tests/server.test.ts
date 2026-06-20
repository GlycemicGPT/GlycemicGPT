/**
 * Integration tests for the Express server endpoints.
 *
 * Uses direct function calls against the app (no HTTP server needed).
 */

import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from "vitest";
import express from "express";
import { InvalidImageError } from "../src/providers/image-utils.js";

// The unauthenticated suite below requires no key in the environment; a
// developer's exported SIDECAR_API_KEY would otherwise 401 every request.
delete process.env.SIDECAR_API_KEY;

// Mock singleton providers
const mockClaudeComplete = vi.fn().mockResolvedValue({
  content: "Hello from Claude",
  model: "claude-sonnet",
});
const mockClaudeStream = vi.fn().mockImplementation(
  async (_messages: unknown, _model: unknown, onChunk?: (text: string) => void) => {
    onChunk?.("Hello ");
    onChunk?.("from ");
    onChunk?.("Claude");
    return { content: "Hello from Claude", model: "claude-sonnet" };
  },
);
const mockClaudeCheckAuth = vi.fn().mockResolvedValue({
  authenticated: true,
  provider: "claude",
  message: "Claude OAuth token configured",
});
const mockCodexCheckAuth = vi.fn().mockResolvedValue({
  authenticated: false,
  provider: "codex",
  message: "No Codex authentication found",
});
// Vision runners: anthropicVision (API key), claude (subscription CLI), codex (CLI).
const mockVisionSupports = vi.fn().mockReturnValue(true);
const mockVisionComplete = vi.fn().mockResolvedValue({
  content: '{"carbs_grams_low": 40, "carbs_grams_high": 55, "confidence": "medium"}',
  model: "claude-sonnet-4-5-20250929",
});
const mockClaudeSupportsVision = vi.fn().mockReturnValue(true);
const mockClaudeCompleteVision = vi.fn().mockResolvedValue({
  content: '{"carbs_grams_low": 10, "carbs_grams_high": 20, "confidence": "low"}',
  model: "claude-sonnet",
});
const mockCodexSupportsVision = vi.fn().mockReturnValue(false);
const mockCodexCompleteVision = vi.fn().mockResolvedValue({
  content: '{"carbs_grams_low": 5, "carbs_grams_high": 15, "confidence": "low"}',
  model: "gpt-4o",
});

vi.mock("../src/providers/index.js", () => ({
  claude: {
    checkAuth: mockClaudeCheckAuth,
    complete: mockClaudeComplete,
    stream: mockClaudeStream,
    supportsVision: mockClaudeSupportsVision,
    completeVision: mockClaudeCompleteVision,
  },
  codex: {
    checkAuth: mockCodexCheckAuth,
    complete: vi.fn(),
    stream: vi.fn(),
    supportsVision: mockCodexSupportsVision,
    completeVision: mockCodexCompleteVision,
  },
  anthropicVision: {
    supportsVision: mockVisionSupports,
    completeVision: mockVisionComplete,
  },
}));

// Mock the token store for auth routes
const mockStoreClaudeToken = vi.fn();
const mockStoreCodexAuth = vi.fn();
const mockReadClaudeToken = vi.fn().mockReturnValue(null);
const mockReadCodexAuth = vi.fn().mockReturnValue(null);

vi.mock("../src/auth/token-store.js", () => ({
  readClaudeToken: mockReadClaudeToken,
  readCodexAuth: mockReadCodexAuth,
  revokeClaudeToken: vi.fn(),
  revokeCodexAuth: vi.fn(),
  storeClaudeToken: mockStoreClaudeToken,
  storeCodexAuth: mockStoreCodexAuth,
}));

// Test helper: invoke Express app without HTTP
async function injectRequest(
  app: express.Express,
  method: "get" | "post",
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<{ status: number; body: unknown; headers: Record<string, string> }> {
  return new Promise((resolve) => {
    const req = {
      method: method.toUpperCase(),
      url: path,
      path,
      ip: "127.0.0.1",
      headers: {
        "content-type": "application/json",
        host: "localhost:3456",
        ...extraHeaders,
      },
      params: {},
      body,
      get: () => undefined,
    } as unknown as express.Request;

    const chunks: string[] = [];
    const headers: Record<string, string> = {};
    let statusCode = 200;

    const res = {
      setHeader: (name: string, value: string) => { headers[name.toLowerCase()] = value; },
      removeHeader: (name: string) => { delete headers[name.toLowerCase()]; },
      status: (code: number) => { statusCode = code; return res; },
      json: (data: unknown) => {
        resolve({ status: statusCode, body: data, headers });
      },
      write: (data: string) => { chunks.push(data); },
      end: () => {
        resolve({ status: statusCode, body: chunks.join(""), headers });
      },
      send: (data: unknown) => {
        resolve({ status: statusCode, body: data, headers });
      },
      sendStatus: (code: number) => {
        resolve({ status: code, body: null, headers });
      },
      flushHeaders: () => {},
    } as unknown as express.Response;

    app(req, res, () => {
      resolve({ status: 404, body: { error: "Not found" }, headers });
    });
  });
}

describe("Server endpoints", () => {
  let app: express.Express;

  beforeAll(async () => {
    const mod = await import("../src/server.js");
    app = mod.app;
  });

  describe("GET /health", () => {
    it("returns health response", async () => {
      const result = await injectRequest(app, "get", "/health");
      expect(result.status).toBe(200);
      const body = result.body as Record<string, unknown>;
      expect(body).toHaveProperty("status");
      expect(body).toHaveProperty("claude_auth");
      expect(body).toHaveProperty("codex_auth");
    });
  });

  describe("GET /v1/models", () => {
    it("returns model list for authenticated providers", async () => {
      const result = await injectRequest(app, "get", "/v1/models");
      expect(result.status).toBe(200);
      const body = result.body as { data: Array<{ id: string }> };
      expect(body.data).toBeDefined();
      expect(body.data.some((m) => m.id.includes("claude"))).toBe(true);
    });
  });

  describe("POST /v1/chat/completions", () => {
    it("rejects request without messages", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {});
      expect(result.status).toBe(400);
      const body = result.body as { error: { message: string } };
      expect(body.error.message).toContain("messages is required");
    });

    it("rejects empty messages array", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [],
      });
      expect(result.status).toBe(400);
    });

    it("rejects messages with invalid role", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [{ role: "admin", content: "test" }],
      });
      expect(result.status).toBe(400);
      const body = result.body as { error: { message: string } };
      expect(body.error.message).toContain("role must be");
    });

    it("rejects messages with non-string content", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [{ role: "user", content: 123 }],
      });
      expect(result.status).toBe(400);
      const body = result.body as { error: { message: string } };
      expect(body.error.message).toContain("content must be a string");
    });

    it("returns non-streaming completion", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [{ role: "user", content: "Hello" }],
        stream: false,
      });
      expect(result.status).toBe(200);
      const body = result.body as {
        id: string;
        choices: Array<{ message: { content: string } }>;
      };
      expect(body.id).toMatch(/^chatcmpl-/);
      expect(body.choices[0].message.content).toBe("Hello from Claude");
    });

    it("returns streaming completion as SSE", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [{ role: "user", content: "Hello" }],
        stream: true,
      });
      expect(result.headers["content-type"]).toBe("text/event-stream");
      const sseData = result.body as string;
      expect(sseData).toContain("data:");
      expect(sseData).toContain("[DONE]");
    });
  });

  describe("POST /v1/chat/completions (vision routing)", () => {
    const PNG_DATA_URL =
      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWqM7HQAAAABJRU5ErkJggg==";

    const imageRequest = (model?: string) => ({
      ...(model ? { model } : {}),
      messages: [
        {
          role: "user",
          content: [
            { type: "image_url", image_url: { url: PNG_DATA_URL } },
            { type: "text", text: "Estimate the carbs." },
          ],
        },
      ],
    });

    beforeEach(() => {
      mockVisionSupports.mockReturnValue(true);
      mockClaudeSupportsVision.mockReturnValue(true);
      mockCodexSupportsVision.mockReturnValue(false);
      mockVisionComplete.mockClear();
      mockClaudeCompleteVision.mockClear();
      mockCodexCompleteVision.mockClear();
      mockClaudeComplete.mockClear();
    });

    it("prefers the Anthropic API-key vision path for a Claude model", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", imageRequest());
      expect(result.status).toBe(200);
      const body = result.body as { choices: Array<{ message: { content: string } }> };
      expect(body.choices[0].message.content).toContain("carbs_grams_low");
      expect(mockVisionComplete).toHaveBeenCalledTimes(1);
      expect(mockClaudeCompleteVision).not.toHaveBeenCalled();
      expect(mockClaudeComplete).not.toHaveBeenCalled();
    });

    it("falls back to the Claude subscription CLI when no API key is configured", async () => {
      mockVisionSupports.mockReturnValue(false); // no Anthropic API key
      const result = await injectRequest(app, "post", "/v1/chat/completions", imageRequest());
      expect(result.status).toBe(200);
      expect(mockClaudeCompleteVision).toHaveBeenCalledTimes(1);
      expect(mockVisionComplete).not.toHaveBeenCalled();
    });

    it("routes a Codex/GPT model image request to the Codex provider", async () => {
      mockCodexSupportsVision.mockReturnValue(true);
      const result = await injectRequest(app, "post", "/v1/chat/completions", imageRequest("gpt-4o"));
      expect(result.status).toBe(200);
      expect(mockCodexCompleteVision).toHaveBeenCalledTimes(1);
      expect(mockVisionComplete).not.toHaveBeenCalled();
      expect(mockClaudeCompleteVision).not.toHaveBeenCalled();
    });

    it("keeps text-only content arrays on the CLI text path", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [{ role: "user", content: [{ type: "text", text: "Hello" }] }],
      });
      expect(result.status).toBe(200);
      const body = result.body as { choices: Array<{ message: { content: string } }> };
      expect(body.choices[0].message.content).toBe("Hello from Claude");
      expect(mockVisionComplete).not.toHaveBeenCalled();
    });

    it("returns the 422 vision_unavailable fallback when no provider can do vision", async () => {
      mockVisionSupports.mockReturnValue(false);
      mockClaudeSupportsVision.mockReturnValue(false);
      const result = await injectRequest(app, "post", "/v1/chat/completions", imageRequest());
      expect(result.status).toBe(422);
      const body = result.body as { error: { type: string; code: string } };
      expect(body.error.type).toBe("vision_unavailable");
      expect(body.error.code).toBe("vision_unavailable");
    });

    it("maps an invalid image to a 400 invalid_request_error", async () => {
      mockVisionComplete.mockRejectedValueOnce(
        new InvalidImageError("image_url must be a base64 data: URL"),
      );
      const result = await injectRequest(app, "post", "/v1/chat/completions", imageRequest());
      expect(result.status).toBe(400);
      const body = result.body as { error: { type: string } };
      expect(body.error.type).toBe("invalid_request_error");
    });

    it("rejects a malformed image part before reaching the provider", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [{ role: "user", content: [{ type: "image_url", image_url: {} }] }],
      });
      expect(result.status).toBe(400);
      expect(mockVisionComplete).not.toHaveBeenCalled();
    });

    it("rejects an image on a non-user role", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [
          { role: "system", content: [{ type: "image_url", image_url: { url: PNG_DATA_URL } }] },
        ],
      });
      expect(result.status).toBe(400);
      const body = result.body as { error: { message: string } };
      expect(body.error.message).toContain("only allowed on a user message");
    });

    it("rejects an empty content array", async () => {
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [{ role: "user", content: [] }],
      });
      expect(result.status).toBe(400);
    });

    it("returns 400 (not 422) for a malformed image even when no runner exists", async () => {
      mockVisionSupports.mockReturnValue(false);
      mockClaudeSupportsVision.mockReturnValue(false);
      const result = await injectRequest(app, "post", "/v1/chat/completions", {
        messages: [
          { role: "user", content: [{ type: "image_url", image_url: { url: "data:image/png;base64,abc" } }] },
        ],
      });
      expect(result.status).toBe(400); // image validation happens before runner selection
    });
  });

  describe("GET /auth/status", () => {
    it("returns auth status for both providers", async () => {
      const result = await injectRequest(app, "get", "/auth/status");
      expect(result.status).toBe(200);
      const body = result.body as {
        claude: { authenticated: boolean };
        codex: { authenticated: boolean };
      };
      expect(body).toHaveProperty("claude");
      expect(body).toHaveProperty("codex");
    });
  });

  describe("POST /auth/start", () => {
    it("returns auth method info for claude", async () => {
      const result = await injectRequest(app, "post", "/auth/start", {
        provider: "claude",
      });
      expect(result.status).toBe(200);
      const body = result.body as { provider: string; auth_method: string; instructions: string };
      expect(body.provider).toBe("claude");
      expect(body.auth_method).toBe("token_paste");
      expect(body.instructions).toContain("claude-code");
    });

    it("returns auth method info for codex", async () => {
      const result = await injectRequest(app, "post", "/auth/start", {
        provider: "codex",
      });
      expect(result.status).toBe(200);
      const body = result.body as { provider: string; auth_method: string; instructions: string };
      expect(body.provider).toBe("codex");
      expect(body.auth_method).toBe("token_paste");
      expect(body.instructions).toContain("codex");
    });

    it("rejects invalid provider", async () => {
      const result = await injectRequest(app, "post", "/auth/start", {
        provider: "invalid",
      });
      expect(result.status).toBe(400);
    });
  });

  describe("POST /auth/token", () => {
    it("stores claude token", async () => {
      const result = await injectRequest(app, "post", "/auth/token", {
        provider: "claude",
        token: "test-claude-token-dummy-value-long-enough",
      });
      expect(result.status).toBe(200);
      const body = result.body as { success: boolean; provider: string };
      expect(body.success).toBe(true);
      expect(body.provider).toBe("claude");
      expect(mockStoreClaudeToken).toHaveBeenCalledWith("test-claude-token-dummy-value-long-enough");
    });

    it("stores codex token", async () => {
      const result = await injectRequest(app, "post", "/auth/token", {
        provider: "codex",
        token: "test-codex-token-dummy-value-long-enough",
      });
      expect(result.status).toBe(200);
      const body = result.body as { success: boolean; provider: string };
      expect(body.success).toBe(true);
      expect(body.provider).toBe("codex");
      expect(mockStoreCodexAuth).toHaveBeenCalledWith({
        accessToken: "test-codex-token-dummy-value-long-enough",
      });
    });

    it("rejects missing token", async () => {
      const result = await injectRequest(app, "post", "/auth/token", {
        provider: "claude",
      });
      expect(result.status).toBe(400);
    });

    it("rejects token that is too short", async () => {
      const result = await injectRequest(app, "post", "/auth/token", {
        provider: "claude",
        token: "short",
      });
      expect(result.status).toBe(400);
    });

    it("rejects invalid provider", async () => {
      const result = await injectRequest(app, "post", "/auth/token", {
        provider: "invalid",
        token: "test-token-dummy-value-long-enough",
      });
      expect(result.status).toBe(400);
    });
  });

  describe("POST /auth/revoke", () => {
    it("revokes claude auth", async () => {
      const result = await injectRequest(app, "post", "/auth/revoke", {
        provider: "claude",
      });
      expect(result.status).toBe(200);
      const body = result.body as { revoked: boolean; provider: string };
      expect(body.revoked).toBe(true);
      expect(body.provider).toBe("claude");
    });

    it("revokes codex auth", async () => {
      const result = await injectRequest(app, "post", "/auth/revoke", {
        provider: "codex",
      });
      expect(result.status).toBe(200);
      const body = result.body as { revoked: boolean; provider: string };
      expect(body.revoked).toBe(true);
      expect(body.provider).toBe("codex");
    });

    it("rejects invalid provider", async () => {
      const result = await injectRequest(app, "post", "/auth/revoke", {
        provider: "invalid",
      });
      expect(result.status).toBe(400);
    });
  });

  describe("Security headers", () => {
    it("sets security headers on responses", async () => {
      const result = await injectRequest(app, "get", "/health");
      expect(result.headers["x-content-type-options"]).toBe("nosniff");
      expect(result.headers["x-frame-options"]).toBe("DENY");
    });
  });
});

describe("Bearer authentication (SIDECAR_API_KEY set)", () => {
  let authedApp: express.Express;
  const TEST_KEY = "test-sidecar-key";

  beforeAll(async () => {
    vi.resetModules();
    vi.stubEnv("SIDECAR_API_KEY", TEST_KEY);
    const mod = await import("../src/server.js");
    authedApp = mod.app;
  });

  afterAll(() => {
    vi.unstubAllEnvs();
  });

  it("rejects requests without an Authorization header", async () => {
    const result = await injectRequest(authedApp, "get", "/v1/models");
    expect(result.status).toBe(401);
    const body = result.body as { error: { type: string } };
    expect(body.error.type).toBe("authentication_error");
  });

  it("rejects requests with a wrong bearer token", async () => {
    const result = await injectRequest(authedApp, "get", "/v1/models", undefined, {
      authorization: "Bearer wrong-key",
    });
    expect(result.status).toBe(401);
  });

  it("rejects a token of different length without throwing", async () => {
    const result = await injectRequest(authedApp, "get", "/v1/models", undefined, {
      authorization: `Bearer ${TEST_KEY}-and-more`,
    });
    expect(result.status).toBe(401);
  });

  it("accepts requests with the correct bearer token", async () => {
    const result = await injectRequest(authedApp, "get", "/v1/models", undefined, {
      authorization: `Bearer ${TEST_KEY}`,
    });
    expect(result.status).toBe(200);
  });

  it("rejects auth-route requests without a token", async () => {
    const result = await injectRequest(authedApp, "post", "/auth/revoke", {
      provider: "claude",
    });
    expect(result.status).toBe(401);
  });

  it("leaves /health reachable without a token (Docker healthcheck)", async () => {
    const result = await injectRequest(authedApp, "get", "/health");
    expect(result.status).toBe(200);
  });
});
