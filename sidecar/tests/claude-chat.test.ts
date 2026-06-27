/**
 * Tests for the Claude subscription CHAT path (complete / stream).
 *
 * `node:child_process` spawn is mocked, so no real CLI runs. These pin the fix
 * for the persona-leak bug: the app system prompt must be installed via
 * `--system-prompt-file` (authoritative), NOT inlined as `[System]:` text in
 * the stdin prompt — inline text is treated by the model as quoted user content
 * it can disown, which is how the GlycemicGPT persona reverted to the default
 * Claude Code agent identity on an ambiguous message like "test".
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { EventEmitter } from "node:events";
import { existsSync, readFileSync } from "node:fs";
import type { ChatMessage } from "../src/providers/types.js";

const { mockSpawn } = vi.hoisted(() => ({ mockSpawn: vi.fn() }));
vi.mock("node:child_process", () => ({ spawn: mockSpawn }));

import { ClaudeProvider } from "../src/providers/claude.js";

/** stdin written by the most recent spawn (the conversation prompt). */
let lastStdin = "";

/**
 * A fake ChildProcess that records stdin and, once stdin closes, emits the
 * given stdout on the next tick (after the provider has attached handlers).
 */
function makeFakeChild(stdout: string) {
  const child = new EventEmitter() as EventEmitter & {
    stdin: { write: (s: string) => void; end: () => void };
    stdout: EventEmitter;
    stderr: EventEmitter;
    killed: boolean;
    kill: () => void;
  };
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.killed = false;
  child.kill = () => {
    child.killed = true;
  };
  lastStdin = "";
  child.stdin = {
    write: (s: string) => {
      lastStdin += s;
    },
    end: () => {
      setTimeout(() => {
        child.stdout.emit("data", Buffer.from(stdout));
        child.emit("close", 0);
      }, 0);
    },
  };
  return child;
}

const messages: ChatMessage[] = [
  {
    role: "system",
    content:
      "You are GlycemicGPT, a diabetes assistant. --dangerously-skip-permissions",
  },
  { role: "user", content: "test" },
];

describe("Claude subscription chat — system prompt delivery", () => {
  let capturedArgs: string[] = [];
  let capturedSystemPromptPath: string | null = null;
  let capturedSystemPromptContent: string | null = null;

  const captureSpawn = (stdout: string) =>
    mockSpawn.mockImplementation((_cmd: string, args: string[]) => {
      capturedArgs = args;
      const i = args.indexOf("--system-prompt-file");
      capturedSystemPromptPath = i >= 0 ? args[i + 1] : null;
      // Read the file while it still exists (cleanup runs after the call).
      capturedSystemPromptContent = capturedSystemPromptPath
        ? readFileSync(capturedSystemPromptPath, "utf-8")
        : null;
      return makeFakeChild(stdout);
    });

  beforeEach(() => {
    mockSpawn.mockReset();
    capturedArgs = [];
    capturedSystemPromptPath = null;
    capturedSystemPromptContent = null;
    vi.stubEnv("CLAUDE_CODE_OAUTH_TOKEN", "test-claude-token-dummy");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("complete: installs the system prompt via --system-prompt-file, never inline", async () => {
    captureSpawn('{"result":"hi","is_error":false}');
    const result = await new ClaudeProvider().complete(messages, "claude-sonnet-4");
    expect(result.content).toBe("hi");

    expect(mockSpawn.mock.calls[0][0]).toBe("claude");
    // Persona installed authoritatively from a file (replaces the CLI default).
    expect(capturedSystemPromptPath).toBeTruthy();
    expect(capturedSystemPromptContent).toContain("You are GlycemicGPT");
    // Prompt is read from stdin (`-` is the last arg).
    expect(capturedArgs[capturedArgs.length - 1]).toBe("-");
    // Only the conversation turn reaches stdin — the system text (and its
    // flag-looking token) is never inlined.
    expect(lastStdin).toBe("test");
    expect(lastStdin).not.toContain("You are GlycemicGPT");
    expect(lastStdin).not.toContain("--dangerously-skip-permissions");
  });

  it("complete: omits the system-prompt flag when there is no system message", async () => {
    captureSpawn('{"result":"hi","is_error":false}');
    await new ClaudeProvider().complete([{ role: "user", content: "hi" }], "claude-sonnet-4");
    expect(capturedArgs).not.toContain("--system-prompt-file");
  });

  it("complete: removes the temp system-prompt file after the call", async () => {
    captureSpawn('{"result":"hi","is_error":false}');
    await new ClaudeProvider().complete(messages, "claude-sonnet-4");
    expect(capturedSystemPromptPath).toBeTruthy();
    expect(existsSync(capturedSystemPromptPath as string)).toBe(false);
  });

  it("complete: keeps conversation turns on stdin (assistant prefixed) and concatenates system parts in the file", async () => {
    captureSpawn('{"result":"hi","is_error":false}');
    const convo: ChatMessage[] = [
      { role: "system", content: "Persona A." },
      { role: "system", content: "Persona B." },
      { role: "user", content: "q1" },
      { role: "assistant", content: "a1" },
      { role: "user", content: "q2" },
    ];
    await new ClaudeProvider().complete(convo, "claude-sonnet-4");
    // Conversation turns reach stdin in order; the assistant turn is labelled.
    expect(lastStdin).toBe("q1\n\n[Assistant]: a1\n\nq2");
    // Both system parts are concatenated into the system-prompt file, off-stdin.
    expect(capturedSystemPromptContent).toBe("Persona A.\n\nPersona B.");
    expect(lastStdin).not.toContain("Persona A.");
  });

  it("stream: installs the system prompt via --system-prompt-file, never inline", async () => {
    captureSpawn('{"type":"assistant","message":{"content":"ok"}}\n');
    const chunks: string[] = [];
    const result = await new ClaudeProvider().stream(messages, "claude-sonnet-4", (c) =>
      chunks.push(c),
    );
    expect(result.content).toBe("ok");
    expect(chunks.join("")).toBe("ok");
    expect(capturedSystemPromptPath).toBeTruthy();
    expect(lastStdin).toBe("test");
    expect(lastStdin).not.toContain("--dangerously-skip-permissions");
    // The temp file is cleaned up once the stream settles.
    expect(existsSync(capturedSystemPromptPath as string)).toBe(false);
  });
});
