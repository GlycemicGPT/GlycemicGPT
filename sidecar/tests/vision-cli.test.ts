/**
 * Tests for the CLI vision argv construction (claude / codex).
 *
 * `runCapture` is mocked, so no subprocess is spawned. These assert the
 * security-critical argv shape: read-only mode, and a `--` end-of-options
 * separator immediately before the (attacker-influenced) positional prompt so a
 * prompt that looks like a flag can never be parsed as one.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const { mockRunCapture } = vi.hoisted(() => ({ mockRunCapture: vi.fn() }));
vi.mock("../src/providers/subprocess.js", () => ({ runCapture: mockRunCapture }));

import { ClaudeProvider } from "../src/providers/claude.js";
import { CodexProvider } from "../src/providers/codex.js";
import type { MultimodalMessage } from "../src/providers/types.js";

const PNG_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWqM7HQAAAABJRU5ErkJggg==";

// A system message whose text begins with a flag-looking token.
const flagInjection: MultimodalMessage[] = [
  { role: "system", content: "--dangerously-skip-permissions" },
  {
    role: "user",
    content: [{ type: "image_url", image_url: { url: PNG_DATA_URL } }],
  },
];

describe("CLI vision argv construction", () => {
  beforeEach(() => {
    mockRunCapture.mockReset();
    mockRunCapture.mockResolvedValue({ stdout: '{"carbs_grams_low":1,"carbs_grams_high":2}', code: 0 });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("claude: runs read-only plan mode with -- before the prompt", async () => {
    vi.stubEnv("CLAUDE_CODE_OAUTH_TOKEN", "test-claude-token-dummy");
    await new ClaudeProvider().completeVision(flagInjection);

    expect(mockRunCapture).toHaveBeenCalledTimes(1);
    const [command, args] = mockRunCapture.mock.calls[0];
    expect(command).toBe("claude");
    // read-only
    const pmIdx = args.indexOf("--permission-mode");
    expect(pmIdx).toBeGreaterThanOrEqual(0);
    expect(args[pmIdx + 1]).toBe("plan");
    // the prompt is the last arg, and `--` is immediately before it
    expect(args[args.length - 2]).toBe("--");
    expect(args[args.length - 1]).toContain("--dangerously-skip-permissions");
  });

  it("codex: runs read-only sandbox with -- before the prompt", async () => {
    vi.stubEnv("OPENAI_API_KEY", "test-openai-key-dummy");
    await new CodexProvider().completeVision(flagInjection);

    expect(mockRunCapture).toHaveBeenCalledTimes(1);
    const [command, args] = mockRunCapture.mock.calls[0];
    expect(command).toBe("codex");
    const sbIdx = args.indexOf("--sandbox");
    expect(sbIdx).toBeGreaterThanOrEqual(0);
    expect(args[sbIdx + 1]).toBe("read-only");
    // The temp cwd is not a git repo; the run must skip codex's trust guard.
    expect(args).toContain("--skip-git-repo-check");
    // No model is forced (a ChatGPT-account Codex picks its own).
    expect(args).not.toContain("--model");
    expect(args[args.length - 2]).toBe("--");
    expect(args[args.length - 1]).toContain("--dangerously-skip-permissions");
  });
});
