/**
 * Tests for Claude and Codex provider wrappers.
 *
 * These test the provider logic (model mapping, auth check, message formatting)
 * without actually spawning CLI subprocesses.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

describe("ClaudeProvider", () => {
  let tempDir: string;
  const originalEnv = { ...process.env };

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "claude-test-"));
    process.env.TOKEN_DIR = tempDir;
    vi.resetModules();
  });

  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true });
    process.env = { ...originalEnv };
  });

  it("reports unauthenticated when no token exists", async () => {
    delete process.env.CLAUDE_CODE_OAUTH_TOKEN;
    const { ClaudeProvider } = await import("../src/providers/claude.js");
    const provider = new ClaudeProvider();
    const state = await provider.checkAuth();
    expect(state.authenticated).toBe(false);
    expect(state.provider).toBe("claude");
  });

  it("reports authenticated when env token is set", async () => {
    process.env.CLAUDE_CODE_OAUTH_TOKEN = "test-claude-token-dummy";
    const { ClaudeProvider } = await import("../src/providers/claude.js");
    const provider = new ClaudeProvider();
    const state = await provider.checkAuth();
    expect(state.authenticated).toBe(true);
  });

  it("reports authenticated when token file exists", async () => {
    delete process.env.CLAUDE_CODE_OAUTH_TOKEN;
    writeFileSync(join(tempDir, "claude_token"), "test-claude-file-token-dummy");
    const { ClaudeProvider } = await import("../src/providers/claude.js");
    const provider = new ClaudeProvider();
    const state = await provider.checkAuth();
    expect(state.authenticated).toBe(true);
  });

  it("resolves known model names", async () => {
    const { resolveModel } = await import("../src/providers/claude.js");
    expect(resolveModel("claude-sonnet-4")).toBe("sonnet");
    expect(resolveModel("claude-opus-4")).toBe("opus");
    expect(resolveModel("claude-haiku-4")).toBe("haiku");
    expect(resolveModel()).toBe("sonnet"); // default
  });

  it("rejects unknown model names", async () => {
    const { resolveModel } = await import("../src/providers/claude.js");
    expect(() => resolveModel("gpt-4o")).toThrow("Unsupported model");
    expect(() => resolveModel("--dangerously-skip-permissions")).toThrow("Unsupported model");
  });

  it("supportsVision tracks subscription-token availability", async () => {
    delete process.env.CLAUDE_CODE_OAUTH_TOKEN;
    const { ClaudeProvider } = await import("../src/providers/claude.js");
    expect(new ClaudeProvider().supportsVision()).toBe(false);
    process.env.CLAUDE_CODE_OAUTH_TOKEN = "test-claude-token-dummy";
    expect(new ClaudeProvider().supportsVision()).toBe(true);
  });

  it("completeVision throws VisionUnavailableError without a token", async () => {
    delete process.env.CLAUDE_CODE_OAUTH_TOKEN;
    const { ClaudeProvider } = await import("../src/providers/claude.js");
    const { VisionUnavailableError } = await import("../src/providers/image-utils.js");
    const messages = [
      { role: "user" as const, content: [{ type: "image_url" as const, image_url: { url: "data:image/png;base64,AAAA" } }] },
    ];
    await expect(new ClaudeProvider().completeVision(messages)).rejects.toBeInstanceOf(
      VisionUnavailableError,
    );
  });
});

describe("CodexProvider", () => {
  let tempDir: string;
  const originalEnv = { ...process.env };

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "codex-test-"));
    process.env.CODEX_HOME = tempDir;
    vi.resetModules();
  });

  afterEach(() => {
    rmSync(tempDir, { recursive: true, force: true });
    process.env = { ...originalEnv };
  });

  it("reports unauthenticated when no auth file exists", async () => {
    delete process.env.OPENAI_API_KEY;
    const { CodexProvider } = await import("../src/providers/codex.js");
    const provider = new CodexProvider();
    const state = await provider.checkAuth();
    expect(state.authenticated).toBe(false);
    expect(state.provider).toBe("codex");
  });

  it("reports authenticated when OPENAI_API_KEY is set", async () => {
    process.env.OPENAI_API_KEY = "test-openai-key-dummy";
    const { CodexProvider } = await import("../src/providers/codex.js");
    const provider = new CodexProvider();
    const state = await provider.checkAuth();
    expect(state.authenticated).toBe(true);
  });

  it("reports authenticated when auth.json exists with valid token", async () => {
    delete process.env.OPENAI_API_KEY;
    writeFileSync(
      join(tempDir, "auth.json"),
      JSON.stringify({ accessToken: "test-codex-token-dummy", expiresAt: 9999999999 }),
    );
    const { CodexProvider } = await import("../src/providers/codex.js");
    const provider = new CodexProvider();
    const state = await provider.checkAuth();
    expect(state.authenticated).toBe(true);
  });

  it("reports unauthenticated when auth.json token is expired", async () => {
    delete process.env.OPENAI_API_KEY;
    writeFileSync(
      join(tempDir, "auth.json"),
      JSON.stringify({ accessToken: "test-codex-token-dummy", expiresAt: 1000000000 }),
    );
    const { CodexProvider } = await import("../src/providers/codex.js");
    const provider = new CodexProvider();
    const state = await provider.checkAuth();
    expect(state.authenticated).toBe(false);
  });

  it("resolves known model names", async () => {
    const { resolveModel } = await import("../src/providers/codex.js");
    expect(resolveModel("gpt-4o")).toBe("gpt-4o");
    expect(resolveModel("o3-mini")).toBe("o3-mini");
    expect(resolveModel()).toBe("gpt-4o"); // default
  });

  it("rejects unknown model names", async () => {
    const { resolveModel } = await import("../src/providers/codex.js");
    expect(() => resolveModel("claude-sonnet-4")).toThrow("Unsupported model");
    expect(() => resolveModel("--some-flag")).toThrow("Unsupported model");
  });

  it("supportsVision tracks Codex auth availability", async () => {
    delete process.env.OPENAI_API_KEY;
    const { CodexProvider } = await import("../src/providers/codex.js");
    expect(new CodexProvider().supportsVision()).toBe(false);
    process.env.OPENAI_API_KEY = "test-openai-key-dummy";
    expect(new CodexProvider().supportsVision()).toBe(true);
  });

  it("completeVision throws VisionUnavailableError without auth", async () => {
    delete process.env.OPENAI_API_KEY;
    const { CodexProvider } = await import("../src/providers/codex.js");
    const { VisionUnavailableError } = await import("../src/providers/image-utils.js");
    const messages = [
      { role: "user" as const, content: [{ type: "image_url" as const, image_url: { url: "data:image/png;base64,AAAA" } }] },
    ];
    await expect(new CodexProvider().completeVision(messages)).rejects.toBeInstanceOf(
      VisionUnavailableError,
    );
  });
});
