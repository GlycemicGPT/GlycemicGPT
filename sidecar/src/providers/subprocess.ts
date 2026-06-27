/**
 * Shared subprocess capture for the CLI vision paths.
 *
 * Spawns a command from an argv array (never a shell) and collects stdout with a
 * timeout and stdout/stderr size caps. The CLI vision providers (claude.ts,
 * codex.ts) differ only in their argv and how they map the result, so the
 * spawn/collect plumbing lives here once.
 */

import { spawn } from "node:child_process";

export interface CaptureOptions {
  env: Record<string, string>;
  cwd: string;
  /** Kill and reject after this many ms. */
  timeoutMs: number;
  /** Reject if stdout or stderr exceeds this many bytes. */
  maxBufferBytes: number;
  /** Human label for the start-failure message (e.g. "Claude"). */
  label: string;
}

export interface CaptureResult {
  stdout: string;
  code: number | null;
}

/**
 * Run `command argv...` with stdin closed, capturing stdout. Resolves with the
 * collected stdout and exit code; rejects on spawn error, timeout, or output
 * overflow. The child is always killed before a rejection settles.
 */
export function runCapture(
  command: string,
  args: string[],
  opts: CaptureOptions,
): Promise<CaptureResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      env: opts.env,
      cwd: opts.cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stdoutSize = 0;
    let stderrSize = 0;
    let settled = false;

    const fail = (message: string) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (!child.killed) child.kill();
      reject(new Error(message));
    };

    const timer = setTimeout(() => fail("AI provider request timed out"), opts.timeoutMs);

    child.stdout?.on("data", (chunk: Buffer) => {
      stdoutSize += chunk.length;
      if (stdoutSize > opts.maxBufferBytes) {
        fail("AI provider response too large");
        return;
      }
      stdout += chunk.toString();
    });
    child.stderr?.on("data", (chunk: Buffer) => {
      stderrSize += chunk.length;
      if (stderrSize > opts.maxBufferBytes) {
        fail("AI provider error output too large");
      }
    });

    child.on("error", (err) => fail(`${opts.label} CLI failed to start: ${err.message}`));

    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ stdout, code });
    });
  });
}
