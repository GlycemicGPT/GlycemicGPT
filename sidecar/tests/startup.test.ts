/**
 * Startup-guard tests: run the real entrypoint as a child process and verify
 * the SIDECAR_API_KEY enforcement that import-based tests cannot reach (the
 * guard only runs when the server is executed directly).
 */

import { describe, it, expect, afterEach } from "vitest";
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const sidecarRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// Resolve through the package exports map so hoisted/workspace installs work;
// "tsx/dist/cli.mjs" is not an exported subpath.
const tsxCli = createRequire(import.meta.url).resolve("tsx/cli");

const children: ChildProcess[] = [];

function startServer(env: Record<string, string>): {
  child: ChildProcess;
  output: () => { stdout: string; stderr: string };
  exited: Promise<number | null>;
} {
  const child = spawn(process.execPath, [tsxCli, "src/server.ts"], {
    cwd: sidecarRoot,
    env: {
      ...process.env,
      SIDECAR_API_KEY: "",
      SIDECAR_ALLOW_UNAUTHENTICATED: "",
      SIDECAR_PORT: "0",
      // Keep transient test listeners off non-loopback interfaces.
      SIDECAR_BIND_HOST: "127.0.0.1",
      ...env,
    },
  });
  children.push(child);
  let stdout = "";
  let stderr = "";
  child.stdout?.on("data", (d: Buffer) => (stdout += d.toString()));
  child.stderr?.on("data", (d: Buffer) => (stderr += d.toString()));
  const exited = new Promise<number | null>((resolve) => child.on("exit", resolve));
  return { child, output: () => ({ stdout, stderr }), exited };
}

async function waitFor(predicate: () => boolean, timeoutMs: number, describeWait: () => string) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) {
      throw new Error(`timed out waiting for: ${describeWait()}`);
    }
    await new Promise((r) => setTimeout(r, 50));
  }
}

afterEach(() => {
  for (const child of children.splice(0)) {
    if (child.exitCode === null) child.kill("SIGKILL");
  }
});

describe("startup guard (child process)", () => {
  it("tsx CLI is present for spawning", () => {
    expect(existsSync(tsxCli)).toBe(true);
  });

  it("refuses to start when SIDECAR_API_KEY is empty", async () => {
    const { output, exited } = startServer({});
    const code = await exited;
    expect(code).toBe(1);
    expect(output().stderr).toContain("FATAL: SIDECAR_API_KEY is not set");
    expect(output().stdout).not.toContain("AI Sidecar listening");
  }, 15000);

  it("starts unauthenticated only with the explicit override, and says so", async () => {
    const { output } = startServer({ SIDECAR_ALLOW_UNAUTHENTICATED: "true" });
    await waitFor(
      () =>
        output().stdout.includes("AI Sidecar listening") &&
        output().stderr.includes("running unauthenticated"),
      10000,
      () => JSON.stringify(output()),
    );
  }, 15000);

  it("starts silently authenticated when a key is provided", async () => {
    const { output } = startServer({ SIDECAR_API_KEY: "startup-test-key" });
    await waitFor(
      () => output().stdout.includes("AI Sidecar listening"),
      10000,
      () => JSON.stringify(output()),
    );
    // Give stderr a beat to flush before asserting the warning is absent.
    await new Promise((r) => setTimeout(r, 250));
    expect(output().stderr).not.toContain("running unauthenticated");
  }, 15000);
});
