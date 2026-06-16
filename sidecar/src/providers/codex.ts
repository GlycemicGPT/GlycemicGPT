/**
 * OpenAI Codex CLI subprocess wrapper.
 *
 * Spawns `codex` CLI and translates between OpenAI chat format and CLI I/O.
 *
 * Authentication: reads from ~/.codex/auth.json (mounted volume) or
 * OPENAI_API_KEY env var as fallback for direct API usage.
 */

import { existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  flattenVisionRequest,
  InvalidImageError,
  VisionUnavailableError,
  writeImagesToTempDir,
} from "./image-utils.js";
import { runCapture } from "./subprocess.js";
import type {
  AIProvider,
  ChatMessage,
  MultimodalMessage,
  ProviderAuthState,
  ProviderResult,
  VisionCompleteOptions,
  VisionRunner,
} from "./types.js";

const CODEX_HOME = process.env.CODEX_HOME || join(
  process.env.HOME || "/home/sidecar",
  ".codex",
);
const AUTH_FILE = join(CODEX_HOME, "auth.json");

/** Subprocess timeout (2 minutes) */
const SUBPROCESS_TIMEOUT_MS = 120_000;
/** Maximum buffer size (10 MB) */
const MAX_BUFFER_BYTES = 10 * 1024 * 1024;
/** Maximum prompt length (100 KB) */
const MAX_PROMPT_LENGTH = 100_000;

/** Strict allowlist of model names */
const MODEL_MAP: Record<string, string> = {
  "gpt-4o": "gpt-4o",
  "gpt-4": "gpt-4",
  "gpt-4-turbo": "gpt-4-turbo",
  "o3-mini": "o3-mini",
  "chatgpt-subscription": "gpt-4o",
};

/** Resolve model name. Rejects unknown models. */
export function resolveModel(model?: string): string {
  if (!model) return "gpt-4o";
  const resolved = MODEL_MAP[model];
  if (!resolved) {
    throw new Error(`Unsupported model: ${model}`);
  }
  return resolved;
}

/** Check whether a Codex credential (ChatGPT account or API key) is configured. */
function getAuthState(): { authenticated: boolean } {
  if (process.env.OPENAI_API_KEY) {
    return { authenticated: true };
  }

  try {
    if (existsSync(AUTH_FILE)) {
      const data = JSON.parse(readFileSync(AUTH_FILE, "utf-8"));
      // ChatGPT-account login (current codex): tokens.access_token. The CLI
      // refreshes the access token itself, so presence is sufficient.
      if (data?.tokens?.access_token) {
        return { authenticated: true };
      }
      // An API key stored in auth.json.
      if (data?.OPENAI_API_KEY) {
        return { authenticated: true };
      }
      // Legacy shape: a top-level accessToken with an optional expiry.
      if (data?.accessToken) {
        if (data.expiresAt && Date.now() / 1000 > data.expiresAt) {
          return { authenticated: false };
        }
        return { authenticated: true };
      }
    }
  } catch {
    // File unreadable or invalid JSON
  }
  return { authenticated: false };
}

/** Flatten messages into a prompt for the CLI */
function messagesToPrompt(messages: ChatMessage[]): string {
  const prompt = messages
    .map((m) => {
      if (m.role === "system") return `[System]: ${m.content}`;
      if (m.role === "user") return m.content;
      return `[Assistant]: ${m.content}`;
    })
    .join("\n\n");

  if (prompt.length > MAX_PROMPT_LENGTH) {
    throw new Error(
      `Prompt too long (${prompt.length} chars, max ${MAX_PROMPT_LENGTH})`,
    );
  }
  return prompt;
}

/**
 * Extract the assistant's final message from `codex exec --json` JSONL output.
 * The clean reply is the text of each `agent_message` item; non-JSON lines
 * (e.g. the CLI's "Reading additional input…" notice) are ignored.
 */
export function extractCodexMessage(stdout: string): string {
  const parts: string[] = [];
  for (const line of stdout.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const event = JSON.parse(trimmed);
      if (
        event?.type === "item.completed" &&
        event?.item?.type === "agent_message" &&
        typeof event.item.text === "string"
      ) {
        parts.push(event.item.text);
      }
    } catch {
      // Not a JSON event line — skip.
    }
  }
  return parts.join("\n").trim();
}

/**
 * Run the Codex CLI non-interactively for a text turn:
 * `codex exec --json --sandbox read-only --skip-git-repo-check -- <prompt>`.
 *
 * Mirrors the vision path (runCodexVision): read-only sandbox, an end-of-options
 * `--` before the (attacker-influenced) prompt, and NO forced `--model` — a
 * ChatGPT-account Codex only accepts its own models (e.g. gpt-5.5) and rejects
 * API names like gpt-4o. `--json` yields structured events so we return the
 * agent's final message without the session preamble / token-usage noise that
 * the plain text output carries.
 */
async function runCodexExec(prompt: string): Promise<ProviderResult> {
  const env: Record<string, string> = { ...process.env } as Record<string, string>;
  env.CODEX_HOME = CODEX_HOME;
  const { stdout, code } = await runCapture(
    "codex",
    ["exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "--", prompt],
    {
      env,
      cwd: tmpdir(),
      timeoutMs: SUBPROCESS_TIMEOUT_MS,
      maxBufferBytes: MAX_BUFFER_BYTES,
      label: "Codex",
    },
  );
  if (code !== 0) {
    throw new Error("AI provider returned an error");
  }
  const content = extractCodexMessage(stdout);
  if (!content) {
    throw new Error("AI provider returned no usable output");
  }
  return { content, model: "codex" };
}

/**
 * Run the official `codex` CLI to analyze image files via its native vision
 * support: `codex exec --image <path> "<prompt>"` (the `--image` flag is
 * repeatable, PNG/JPEG). The image is delivered to the model as vision input by
 * the CLI itself — no credential impersonation. Drives the official client the
 * same way the text path does.
 *
 * Note: non-interactive `--image` had bugs fixed in late 2025 (openai/codex
 * #2323, #5773); deployments must pin a current codex version.
 */
async function runCodexVision(
  prompt: string,
  imagePaths: string[],
  imageDir: string,
): Promise<ProviderResult> {
  const env: Record<string, string> = { ...process.env } as Record<string, string>;
  env.CODEX_HOME = CODEX_HOME;

  // Read-only sandbox: the run analyzes the images, it does not modify anything.
  // --skip-git-repo-check: the cwd is a private temp dir (not a git repo), so
  // codex's interactive "trusted directory" guard would otherwise abort.
  // No --model: a ChatGPT-account Codex only accepts its own models (e.g.
  // gpt-5.5) and rejects API model names like gpt-4o, so we let the CLI pick the
  // account-appropriate default rather than forcing one that may be unsupported.
  const args = ["exec", "--sandbox", "read-only", "--skip-git-repo-check"];
  for (const path of imagePaths) {
    args.push("--image", path);
  }
  // End-of-options: the prompt is positional and never parsed as a flag.
  args.push("--", prompt);

  const { stdout, code } = await runCapture("codex", args, {
    env,
    cwd: imageDir,
    timeoutMs: SUBPROCESS_TIMEOUT_MS,
    maxBufferBytes: MAX_BUFFER_BYTES,
    label: "Codex",
  });
  if (code !== 0) {
    throw new Error("AI provider returned an error");
  }
  return { content: stdout.trim(), model: "codex" };
}

export class CodexProvider implements AIProvider, VisionRunner {
  /**
   * Vision is served via the Codex CLI when any Codex credential is configured.
   * `getAuthState()` treats both a ChatGPT-subscription token (`auth.json`) and
   * a raw `OPENAI_API_KEY` as authenticated; the CLI uses whichever it finds.
   */
  supportsVision(): boolean {
    return getAuthState().authenticated;
  }

  async completeVision(
    messages: MultimodalMessage[],
    _options: VisionCompleteOptions = {},
  ): Promise<ProviderResult> {
    if (!getAuthState().authenticated) {
      throw new VisionUnavailableError();
    }
    // Note: neither the requested model nor maxTokens is forwarded on this CLI
    // subscription path — a ChatGPT-account Codex picks its own model and has no
    // output-token cap; the model self-limits.
    const { systemText, userText, images } = flattenVisionRequest(messages);
    if (images.length === 0) {
      throw new InvalidImageError("no image provided for a vision request");
    }
    const prompt = [systemText, userText].filter(Boolean).join("\n\n");
    if (prompt.length > MAX_PROMPT_LENGTH) {
      throw new Error(`Prompt too long (${prompt.length} chars, max ${MAX_PROMPT_LENGTH})`);
    }
    const temp = writeImagesToTempDir(images);
    try {
      return await runCodexVision(prompt, temp.paths, temp.dir);
    } finally {
      temp.cleanup();
    }
  }

  async checkAuth(): Promise<ProviderAuthState> {
    const { authenticated } = getAuthState();
    return {
      authenticated,
      provider: "codex",
      message: authenticated
        ? "Codex authentication configured"
        : "No Codex authentication found",
    };
  }

  async complete(
    messages: ChatMessage[],
    _model?: string,
  ): Promise<ProviderResult> {
    // The prompt carries the system text inline (messagesToPrompt); authoritative
    // persona delivery for codex is tracked separately (Epic 52 M4). The model is
    // not forwarded — a ChatGPT-account Codex picks its own model (see runCodexExec).
    return runCodexExec(messagesToPrompt(messages));
  }

  async stream(
    messages: ChatMessage[],
    _model?: string,
    onChunk?: (text: string) => void,
  ): Promise<ProviderResult> {
    // `codex exec` returns a single final message rather than a token stream, so
    // surface it as one chunk. (The web chat path uses complete(), not stream.)
    const result = await runCodexExec(messagesToPrompt(messages));
    onChunk?.(result.content);
    return result;
  }
}
