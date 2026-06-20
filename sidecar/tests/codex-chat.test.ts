/**
 * Tests for the Codex (ChatGPT subscription) CHAT path.
 *
 * `runCapture` is mocked, so no subprocess runs. These pin the fix that routes
 * chat through `codex exec --json` (the same invocation as the vision path),
 * with NO forced `--model` (a ChatGPT-account Codex rejects API model names like
 * gpt-4o), and that the clean agent message is extracted from the JSONL events
 * rather than returning the raw session preamble / token-usage noise.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { tmpdir } from "node:os";

const { mockRunCapture } = vi.hoisted(() => ({ mockRunCapture: vi.fn() }));
vi.mock("../src/providers/subprocess.js", () => ({ runCapture: mockRunCapture }));

import { CodexProvider, extractCodexMessage } from "../src/providers/codex.js";
import type { ChatMessage } from "../src/providers/types.js";

const AGENT_JSONL = [
  '{"type":"thread.started","thread_id":"t1"}',
  '{"type":"turn.started"}',
  '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hi from chatgpt"}}',
  '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":3}}',
].join("\n");

describe("extractCodexMessage", () => {
  it("returns the agent_message text, ignoring non-JSON lines and other events", () => {
    const raw = "Reading additional input from stdin...\n" + AGENT_JSONL;
    expect(extractCodexMessage(raw)).toBe("hi from chatgpt");
  });

  it("joins multiple agent messages and trims", () => {
    const raw = [
      '{"type":"item.completed","item":{"type":"agent_message","text":"line1"}}',
      '{"type":"item.completed","item":{"type":"agent_message","text":"line2"}}',
    ].join("\n");
    expect(extractCodexMessage(raw)).toBe("line1\nline2");
  });

  it("returns empty when there is no agent_message", () => {
    expect(extractCodexMessage('{"type":"turn.completed"}')).toBe("");
  });

  it("excludes item.completed events whose item.type is not agent_message", () => {
    // codex exec --json also emits reasoning / command_execution / etc. items;
    // only the agent_message text may reach the user-facing reply.
    const raw = [
      '{"type":"item.completed","item":{"type":"reasoning","text":"internal thoughts"}}',
      '{"type":"item.completed","item":{"type":"agent_message","text":"visible reply"}}',
      '{"type":"item.completed","item":{"type":"command_execution","text":"ls -la"}}',
    ].join("\n");
    expect(extractCodexMessage(raw)).toBe("visible reply");
  });
});

describe("CodexProvider.complete — chat via `codex exec`", () => {
  const messages: ChatMessage[] = [
    { role: "system", content: "You are GlycemicGPT." },
    { role: "user", content: "test" },
  ];

  beforeEach(() => {
    mockRunCapture.mockReset();
  });

  it("runs `codex exec --json` read-only, with no forced --model and -- before the prompt", async () => {
    mockRunCapture.mockResolvedValue({ stdout: AGENT_JSONL, code: 0 });

    const result = await new CodexProvider().complete(messages, "gpt-4o");
    // Clean message extracted from the JSONL, not the raw transcript.
    expect(result.content).toBe("hi from chatgpt");
    expect(result.model).toBe("codex");

    expect(mockRunCapture).toHaveBeenCalledTimes(1);
    const [command, args, opts] = mockRunCapture.mock.calls[0];
    expect(command).toBe("codex");
    expect(args.slice(0, 5)).toEqual([
      "exec",
      "--json",
      "--sandbox",
      "read-only",
      "--skip-git-repo-check",
    ]);
    // A ChatGPT-account Codex rejects forced API model names — none must be sent.
    expect(args).not.toContain("--model");
    // End-of-options separator immediately before the positional prompt.
    expect(args[args.length - 2]).toBe("--");
    // The positional prompt carries the flattened system + user text.
    const prompt = args[args.length - 1];
    expect(prompt).toContain("You are GlycemicGPT.");
    expect(prompt).toContain("test");
    // Run isolated (outside any git repo) with codex auth discovery wired up.
    expect(opts.cwd).toBe(tmpdir());
    expect(opts.label).toBe("Codex");
    expect(opts.timeoutMs).toBe(120_000);
    expect(opts.maxBufferBytes).toBe(10 * 1024 * 1024);
    expect(opts.env.CODEX_HOME).toBeTruthy();
  });

  it("throws when codex exits non-zero", async () => {
    mockRunCapture.mockResolvedValue({ stdout: "", code: 1 });
    await expect(new CodexProvider().complete(messages)).rejects.toThrow(
      "AI provider returned an error",
    );
  });

  it("throws 'no usable output' when codex exits 0 but emits no agent_message", async () => {
    mockRunCapture.mockResolvedValue({ stdout: '{"type":"turn.completed"}', code: 0 });
    await expect(new CodexProvider().complete(messages)).rejects.toThrow(
      "AI provider returned no usable output",
    );
  });

  it("rejects an oversize prompt by UTF-8 bytes (not chars) before spawning codex", async () => {
    // 40k multibyte chars = 40k UTF-16 code units (well under the old char cap)
    // but 120k UTF-8 bytes — which would trip an opaque E2BIG at spawn. The
    // byte-measured guard rejects it cleanly and never invokes the CLI.
    const oversize: ChatMessage[] = [{ role: "user", content: "あ".repeat(40_000) }];
    await expect(new CodexProvider().complete(oversize)).rejects.toThrow(
      /Prompt too long \(\d+ bytes/,
    );
    expect(mockRunCapture).not.toHaveBeenCalled();
  });
});

describe("CodexProvider.stream — chat via `codex exec`", () => {
  const messages: ChatMessage[] = [
    { role: "system", content: "You are GlycemicGPT." },
    { role: "user", content: "test" },
  ];

  beforeEach(() => {
    mockRunCapture.mockReset();
  });

  it("emits the extracted message as a single chunk and returns it", async () => {
    mockRunCapture.mockResolvedValue({ stdout: AGENT_JSONL, code: 0 });
    const chunks: string[] = [];
    const result = await new CodexProvider().stream(messages, "gpt-4o", (c) =>
      chunks.push(c),
    );
    // codex exec yields a final message, not a token stream → exactly one chunk.
    expect(chunks).toEqual(["hi from chatgpt"]);
    expect(result.content).toBe("hi from chatgpt");
    expect(result.model).toBe("codex");
  });

  it("throws when codex exits non-zero", async () => {
    mockRunCapture.mockResolvedValue({ stdout: "", code: 1 });
    await expect(
      new CodexProvider().stream(messages, undefined, () => {}),
    ).rejects.toThrow("AI provider returned an error");
  });
});
