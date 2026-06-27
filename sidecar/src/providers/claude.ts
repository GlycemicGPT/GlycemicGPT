/**
 * Claude Code CLI subprocess wrapper.
 *
 * Spawns `claude` CLI in non-interactive mode (`--print --output-format stream-json`)
 * and translates between OpenAI chat format and CLI stdin/stdout.
 *
 * Authentication: reads CLAUDE_CODE_OAUTH_TOKEN from environment or
 * a persisted token file at TOKEN_DIR/claude_token.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

const TOKEN_DIR = process.env.TOKEN_DIR || "/home/sidecar/.config/sidecar";
const CLAUDE_TOKEN_FILE = join(TOKEN_DIR, "claude_token");

/** Subprocess timeout (2 minutes) */
const SUBPROCESS_TIMEOUT_MS = 120_000;
/** Maximum stdout/stderr buffer size (10 MB) */
const MAX_BUFFER_BYTES = 10 * 1024 * 1024;
/** Maximum prompt length (100 KB) */
const MAX_PROMPT_LENGTH = 100_000;

/** Strict allowlist of model names to Claude CLI aliases */
const MODEL_MAP: Record<string, string> = {
  "claude-opus-4": "opus",
  "claude-sonnet-4": "sonnet",
  "claude-haiku-4": "haiku",
  "claude-opus-4-6": "opus",
  "claude-sonnet-4-5": "sonnet",
  "claude-sonnet-4-5-20250929": "sonnet",
  "claude-haiku-4-5": "haiku",
  "claude-haiku-4-5-20251001": "haiku",
  // Allow bare aliases
  opus: "opus",
  sonnet: "sonnet",
  haiku: "haiku",
};

/** Resolve model name to CLI alias. Rejects unknown models. */
export function resolveModel(model?: string): string {
  if (!model) return "sonnet";
  const resolved = MODEL_MAP[model];
  if (!resolved) {
    throw new Error(`Unsupported model: ${model}`);
  }
  return resolved;
}

/** Read the stored OAuth token, preferring env var over file */
function getToken(): string | null {
  const envToken = process.env.CLAUDE_CODE_OAUTH_TOKEN;
  if (envToken) return envToken;

  try {
    if (existsSync(CLAUDE_TOKEN_FILE)) {
      return readFileSync(CLAUDE_TOKEN_FILE, "utf-8").trim();
    }
  } catch {
    // File unreadable — treat as unauthenticated
  }
  return null;
}

interface TempSystemPrompt {
  /** Absolute path of the written system-prompt file. */
  path: string;
  /** Remove the temp file and its directory. Call once the subprocess has
   *  finished reading it (in a finally, or after the spawned CLI settles). */
  cleanup: () => void;
}

/**
 * Write the caller's system prompt to a fresh, private temp file so it can be
 * handed to the CLI via `--system-prompt-file`. The prompt is the app's
 * GlycemicGPT instructions; delivering it as a real system prompt (not inline
 * `[System]:` text in the user turn) is what makes the model actually adopt the
 * persona instead of answering as the default Claude Code agent.
 */
function writeSystemPromptFile(systemPrompt: string): TempSystemPrompt {
  const dir = mkdtempSync(join(tmpdir(), "gg-sys-"));
  chmodSync(dir, 0o700); // private to this process, not reliant on umask
  const path = join(dir, "system-prompt.txt");
  try {
    writeFileSync(path, systemPrompt, { mode: 0o600 });
  } catch (err) {
    rmSync(dir, { recursive: true, force: true });
    throw err;
  }
  return { path, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

/**
 * CLI flag that installs an authoritative system prompt from a file, replacing
 * the CLI's default prompt (which carries Claude Code's identity and dynamic
 * cwd/env sections) so only the app's persona drives the session. Returns no
 * flags when there is no system prompt, leaving the CLI default in place. The
 * prompt is passed by file path, never as an argv value, so its contents can't
 * be parsed as flags.
 */
function systemPromptArgs(systemPromptFile: string | null): string[] {
  return systemPromptFile ? ["--system-prompt-file", systemPromptFile] : [];
}

/**
 * Split chat messages into the authoritative system prompt (delivered via
 * `--system-prompt-file`) and the conversation turns (sent on stdin). System
 * content is deliberately NOT inlined into the conversation: inline `[System]:`
 * text is treated by the model as quoted user content it can disown, which is
 * how the GlycemicGPT persona leaked back to the default Claude Code identity.
 */
function splitSystemPrompt(messages: ChatMessage[]): {
  systemPrompt: string;
  conversation: string;
} {
  const systemParts: string[] = [];
  const turnParts: string[] = [];
  for (const m of messages) {
    if (m.role === "system") {
      systemParts.push(m.content);
    } else if (m.role === "assistant") {
      turnParts.push(`[Assistant]: ${m.content}`);
    } else {
      turnParts.push(m.content);
    }
  }
  const systemPrompt = systemParts.join("\n\n").trim();
  const conversation = turnParts.join("\n\n");
  // Bound the combined payload as the old inline flattening did: the system
  // prompt now travels by file rather than on the user turn, but it still
  // counts against the model's input budget, so cap system + conversation.
  const total = systemPrompt.length + conversation.length;
  if (total > MAX_PROMPT_LENGTH) {
    throw new Error(`Prompt too long (${total} chars, max ${MAX_PROMPT_LENGTH})`);
  }
  return { systemPrompt, conversation };
}

/**
 * Spawn the Claude CLI as a child process.
 * Prompt is passed via stdin (not as a CLI argument) to prevent injection.
 *
 * @param systemPromptFile Path to the app system prompt, installed via
 *   `--system-prompt-file` so the model adopts the GlycemicGPT persona; null
 *   leaves the CLI default in place.
 * @param extraArgs Additional CLI flags (e.g. output format overrides).
 */
function spawnClaude(
  prompt: string,
  model: string,
  systemPromptFile: string | null,
  extraArgs: string[] = [],
): ChildProcess {
  const token = getToken();
  const env: Record<string, string> = { ...process.env } as Record<
    string,
    string
  >;
  if (token) env.CLAUDE_CODE_OAUTH_TOKEN = token;

  const child = spawn(
    "claude",
    [
      "--print",
      "--no-session-persistence",
      "--model",
      model, // Already validated by resolveModel()
      ...systemPromptArgs(systemPromptFile),
      ...extraArgs,
      "-", // Read prompt from stdin
    ],
    {
      env,
      stdio: ["pipe", "pipe", "pipe"],
    },
  );

  // Write prompt to stdin and close
  child.stdin?.write(prompt);
  child.stdin?.end();

  return child;
}

/**
 * Parse a single line of Claude CLI stream-json output and return the
 * text delta (if any).
 *
 * Handles three output shapes from the CLI:
 *   1. `stream_event` wrapping `content_block_delta` (--include-partial-messages)
 *   2. `assistant` with `message.content` as an array of text blocks
 *   3. `content_block_delta` at top level (legacy)
 */
function extractTextDelta(line: string): string | null {
  try {
    const obj = JSON.parse(line);

    // Shape 1: streaming delta wrapped in stream_event
    if (obj?.type === "stream_event") {
      const inner = obj.event;
      if (inner?.type === "content_block_delta" && inner?.delta?.text) {
        return inner.delta.text as string;
      }
    }

    // Shape 2: full assistant message (content can be string or array)
    if (obj?.type === "assistant" && obj?.message?.content) {
      const content = obj.message.content;
      if (typeof content === "string") return content;
      if (Array.isArray(content)) {
        return content
          .filter((b: { type: string; text?: string }) => b.type === "text" && b.text)
          .map((b: { type: string; text: string }) => b.text)
          .join("");
      }
    }

    // Shape 3: top-level content_block_delta (legacy)
    if (obj?.type === "content_block_delta" && obj?.delta?.text) {
      return obj.delta.text as string;
    }
  } catch {
    // Not valid JSON — skip
  }
  return null;
}

/** Kill a child process and clear its timeout */
function cleanupChild(child: ChildProcess, timer: ReturnType<typeof setTimeout>): void {
  clearTimeout(timer);
  if (!child.killed) child.kill();
}

/**
 * Build the positional prompt for the CLI vision path. The model is told the
 * meal photo(s) are on disk and instructed to read them; the user text follows.
 * The system prompt (the carb contract) is delivered separately via
 * `--system-prompt-file`, not inlined here.
 */
function buildVisionPrompt(userText: string, imagePaths: string[]): string {
  const lines: string[] = [];
  lines.push(
    imagePaths.length === 1
      ? `A meal photo has been provided as the file ${imagePaths[0]}. Read that image file and analyze the food shown in it.`
      : `Meal photos have been provided as the files ${imagePaths.join(", ")}. ` +
          "Read those image files and analyze the food shown in them.",
  );
  if (userText) lines.push(userText);
  return lines.join("\n\n");
}

/**
 * Run the official `claude` CLI in read-only plan mode to analyze image files.
 * Plan mode renders the image via the Read tool but cannot Write/Edit/Bash, and
 * the only directory granted is the private temp dir holding the images. This is
 * the sanctioned subscription vision path — no credential impersonation.
 */
async function runClaudeVision(
  prompt: string,
  cliModel: string,
  imageDir: string,
  systemPromptFile: string | null,
): Promise<ProviderResult> {
  const token = getToken();
  const env: Record<string, string> = { ...process.env } as Record<string, string>;
  if (token) env.CLAUDE_CODE_OAUTH_TOKEN = token;

  const { stdout, code } = await runCapture(
    "claude",
    [
      "--print",
      // Don't retain the image prompt in session storage (matches the text path).
      "--no-session-persistence",
      "--model",
      cliModel,
      "--add-dir",
      imageDir,
      // Read-only: Read renders the image; Write/Edit/Bash are blocked.
      "--permission-mode",
      "plan",
      // Install the carb-contract system prompt authoritatively (by file path,
      // never as an argv value) so the model follows it rather than the default
      // Claude Code agent prompt.
      ...systemPromptArgs(systemPromptFile),
      // End-of-options: the prompt is positional and never parsed as a flag.
      "--",
      prompt,
    ],
    { env, cwd: imageDir, timeoutMs: SUBPROCESS_TIMEOUT_MS, maxBufferBytes: MAX_BUFFER_BYTES, label: "Claude" },
  );
  if (code !== 0) {
    throw new Error("AI provider returned an error");
  }
  return { content: stdout.trim(), model: `claude-${cliModel}` };
}

export class ClaudeProvider implements AIProvider, VisionRunner {
  /** Vision is served via the subscription CLI when a token is configured. */
  supportsVision(): boolean {
    return getToken() !== null;
  }

  async completeVision(
    messages: MultimodalMessage[],
    options: VisionCompleteOptions = {},
  ): Promise<ProviderResult> {
    if (getToken() === null) {
      throw new VisionUnavailableError();
    }
    // Note: options.maxTokens is not enforced on this CLI subscription path —
    // `claude --print` has no output-token cap; the model self-limits. (The
    // Anthropic API-key path honors max_tokens.)
    const { systemText, userText, images } = flattenVisionRequest(messages);
    if (images.length === 0) {
      throw new InvalidImageError("no image provided for a vision request");
    }
    const temp = writeImagesToTempDir(images);
    // Allocate the system-prompt temp file inside the try: if it throws (e.g. a
    // transient FS error), the finally still runs temp.cleanup() so the decoded
    // meal-photo bytes never leak under /tmp. (writeImagesToTempDir self-cleans
    // on its own throw, before temp is bound.)
    let sys: TempSystemPrompt | null = null;
    try {
      sys = systemText ? writeSystemPromptFile(systemText) : null;
      const prompt = buildVisionPrompt(userText, temp.paths);
      if (prompt.length > MAX_PROMPT_LENGTH) {
        throw new Error(`Prompt too long (${prompt.length} chars, max ${MAX_PROMPT_LENGTH})`);
      }
      return await runClaudeVision(prompt, resolveModel(options.model), temp.dir, sys?.path ?? null);
    } finally {
      temp.cleanup();
      sys?.cleanup();
    }
  }

  async checkAuth(): Promise<ProviderAuthState> {
    const token = getToken();
    return {
      authenticated: !!token,
      provider: "claude",
      message: token
        ? "Claude OAuth token configured"
        : "No Claude OAuth token found",
    };
  }

  async complete(
    messages: ChatMessage[],
    model?: string,
  ): Promise<ProviderResult> {
    const { systemPrompt, conversation } = splitSystemPrompt(messages);
    const cliModel = resolveModel(model);
    const sys = systemPrompt ? writeSystemPromptFile(systemPrompt) : null;

    return new Promise<ProviderResult>((resolve, reject) => {
      const child = spawnClaude(conversation, cliModel, sys?.path ?? null, [
        "--output-format", "json",
      ]);
      let stdout = "";
      let stdoutSize = 0;
      let stderrSize = 0;

      const timer = setTimeout(() => {
        child.kill();
        reject(new Error("AI provider request timed out"));
      }, SUBPROCESS_TIMEOUT_MS);

      child.stdout?.on("data", (chunk: Buffer) => {
        stdoutSize += chunk.length;
        if (stdoutSize > MAX_BUFFER_BYTES) {
          cleanupChild(child, timer);
          reject(new Error("AI provider response too large"));
          return;
        }
        stdout += chunk.toString();
      });
      child.stderr?.on("data", (chunk: Buffer) => {
        stderrSize += chunk.length;
        if (stderrSize > MAX_BUFFER_BYTES) {
          cleanupChild(child, timer);
          reject(new Error("AI provider error output too large"));
        }
      });

      child.on("error", (err) => {
        clearTimeout(timer);
        reject(new Error(`Claude CLI failed to start: ${err.message}`));
      });

      child.on("close", (code) => {
        clearTimeout(timer);
        if (code !== 0) {
          reject(new Error("AI provider returned an error"));
          return;
        }

        try {
          const result = JSON.parse(stdout.trim());
          if (result.is_error) {
            reject(new Error(result.result || "AI provider returned an error"));
            return;
          }
          resolve({ content: result.result || "", model: `claude-${cliModel}` });
        } catch {
          // Fallback: treat raw stdout as plain text if JSON parsing fails
          resolve({ content: stdout.trim(), model: `claude-${cliModel}` });
        }
      });
    }).finally(() => {
      // Cleanup runs after the Promise settles: the spawned CLI reads the
      // system-prompt file asynchronously, so removing it earlier would race the
      // subprocess. (completeVision uses a synchronous try/finally instead.)
      sys?.cleanup();
    });
  }

  async stream(
    messages: ChatMessage[],
    model?: string,
    onChunk?: (text: string) => void,
  ): Promise<ProviderResult> {
    const { systemPrompt, conversation } = splitSystemPrompt(messages);
    const cliModel = resolveModel(model);
    const sys = systemPrompt ? writeSystemPromptFile(systemPrompt) : null;

    return new Promise<ProviderResult>((resolve, reject) => {
      const child = spawnClaude(conversation, cliModel, sys?.path ?? null, [
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
      ]);
      let buffer = "";
      let content = "";
      let totalSize = 0;

      const timer = setTimeout(() => {
        child.kill();
        reject(new Error("AI provider request timed out"));
      }, SUBPROCESS_TIMEOUT_MS);

      child.stdout?.on("data", (chunk: Buffer) => {
        totalSize += chunk.length;
        if (totalSize > MAX_BUFFER_BYTES) {
          cleanupChild(child, timer);
          reject(new Error("AI provider response too large"));
          return;
        }
        buffer += chunk.toString();
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.trim()) continue;
          const delta = extractTextDelta(line);
          if (delta) {
            content += delta;
            onChunk?.(delta);
          }
        }
      });

      let stderrSize = 0;
      child.stderr?.on("data", (chunk: Buffer) => {
        stderrSize += chunk.length;
        if (stderrSize > MAX_BUFFER_BYTES) {
          cleanupChild(child, timer);
          reject(new Error("AI provider error output too large"));
        }
      });

      child.on("error", (err) => {
        clearTimeout(timer);
        reject(new Error(`Claude CLI failed to start: ${err.message}`));
      });

      child.on("close", (code) => {
        clearTimeout(timer);
        if (buffer.trim()) {
          const delta = extractTextDelta(buffer);
          if (delta) {
            content += delta;
            onChunk?.(delta);
          }
        }

        if (code !== 0 && !content) {
          reject(new Error("AI provider returned an error"));
          return;
        }

        resolve({ content, model: `claude-${cliModel}` });
      });
    }).finally(() => {
      // Cleanup runs after the Promise settles: the spawned CLI reads the
      // system-prompt file asynchronously, so removing it earlier would race the
      // subprocess. (completeVision uses a synchronous try/finally instead.)
      sys?.cleanup();
    });
  }
}
