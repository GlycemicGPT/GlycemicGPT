/**
 * AI Sidecar Express Server
 *
 * Exposes an OpenAI-compatible API backed by Claude Code CLI and Codex CLI
 * subprocesses. Ships as a Docker container alongside the main GlycemicGPT
 * services so subscription users get a zero-config AI experience.
 *
 * Endpoints:
 *   GET  /health              - readiness/liveness check (no auth required)
 *   GET  /v1/models           - list available models
 *   POST /v1/chat/completions - OpenAI-compatible chat (streaming + non-streaming)
 *   GET  /auth/status         - authentication state
 *   POST /auth/start          - return auth method info for a provider
 *   POST /auth/token          - accept token submission
 *   POST /auth/revoke         - revoke stored auth
 */

import express from "express";
import { randomUUID } from "node:crypto";
import { healthHandler } from "./health.js";
import { authRouter } from "./auth/oauth-server.js";
import { claude, codex } from "./providers/index.js";
import type { ChatMessage } from "./providers/types.js";

const app = express();
const PORT = parseInt(process.env.SIDECAR_PORT || "3456", 10);
const BIND_HOST = process.env.SIDECAR_BIND_HOST || "0.0.0.0";
const SIDECAR_API_KEY = process.env.SIDECAR_API_KEY || "";
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || "http://localhost:3000")
  .split(",")
  .map((o) => o.trim())
  .filter((o) => o && o !== "*"); // Reject wildcards

// --- Middleware ---

app.use(express.json({ limit: "256kb" }));

// Security headers
app.use((_req, res, next) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("X-Frame-Options", "DENY");
  res.removeHeader("X-Powered-By");
  next();
});

// CORS -- only set headers when origin matches whitelist
app.use((req, res, next) => {
  const origin = req.headers.origin;
  if (origin && ALLOWED_ORIGINS.includes(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  }
  if (req.method === "OPTIONS") {
    if (origin && ALLOWED_ORIGINS.includes(origin)) {
      res.sendStatus(204);
    } else {
      res.sendStatus(403);
    }
    return;
  }
  next();
});

// Request logging (metadata only, no prompt content)
app.use((req, _res, next) => {
  if (req.path !== "/health") {
    console.log(
      JSON.stringify({
        ts: new Date().toISOString(),
        method: req.method,
        path: req.path,
        ip: req.ip,
      }),
    );
  }
  next();
});

// Bearer token authentication (skip /health for Docker healthchecks)
app.use((req, res, next) => {
  if (req.path === "/health") return next();

  if (SIDECAR_API_KEY) {
    const auth = req.headers.authorization;
    if (!auth || auth !== `Bearer ${SIDECAR_API_KEY}`) {
      res.status(401).json({
        error: { message: "Unauthorized", type: "authentication_error" },
      });
      return;
    }
  }
  next();
});

/** Choose provider based on model name */
function getProvider(model?: string) {
  if (!model) return claude;
  const lower = model.toLowerCase();
  if (lower.includes("gpt") || lower.includes("codex") || lower.includes("o3") || lower.includes("o1")) {
    return codex;
  }
  return claude;
}

/** Validate that messages array contains valid ChatMessage objects */
function validateMessages(
  messages: unknown,
): { valid: true; data: ChatMessage[] } | { valid: false; error: string } {
  if (!Array.isArray(messages) || messages.length === 0) {
    return { valid: false, error: "messages is required and must be a non-empty array" };
  }
  const validRoles = new Set(["system", "user", "assistant"]);
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (!msg || typeof msg !== "object") {
      return { valid: false, error: `messages[${i}] must be an object` };
    }
    if (!validRoles.has(msg.role)) {
      return { valid: false, error: `messages[${i}].role must be system, user, or assistant` };
    }
    if (typeof msg.content !== "string") {
      return { valid: false, error: `messages[${i}].content must be a string` };
    }
  }
  return { valid: true, data: messages as ChatMessage[] };
}

// --- Routes ---

app.get("/health", healthHandler);

app.use("/auth", authRouter);

/** GET /v1/models - List available models */
app.get("/v1/models", async (_req, res) => {
  const [claudeAuth, codexAuth] = await Promise.all([
    claude.checkAuth(),
    codex.checkAuth(),
  ]);

  const models: Array<{ id: string; object: string; owned_by: string }> = [];

  if (claudeAuth.authenticated) {
    models.push(
      { id: "claude-sonnet-4", object: "model", owned_by: "anthropic" },
      { id: "claude-opus-4", object: "model", owned_by: "anthropic" },
      { id: "claude-haiku-4", object: "model", owned_by: "anthropic" },
    );
  }

  if (codexAuth.authenticated) {
    models.push(
      { id: "gpt-4o", object: "model", owned_by: "openai" },
      { id: "gpt-4-turbo", object: "model", owned_by: "openai" },
      { id: "o3-mini", object: "model", owned_by: "openai" },
    );
  }

  res.json({ object: "list", data: models });
});

/** POST /v1/chat/completions - OpenAI-compatible chat */
app.post("/v1/chat/completions", async (req, res) => {
  const body = req.body as Record<string, unknown>;

  // Runtime validation
  const validation = validateMessages(body?.messages);
  if (!validation.valid) {
    res.status(400).json({
      error: { message: validation.error, type: "invalid_request_error" },
    });
    return;
  }
  const messages = validation.data;
  const model = typeof body.model === "string" ? body.model : undefined;
  const stream = body.stream === true;

  const provider = getProvider(model);

  // Check auth
  const authState = await provider.checkAuth();
  if (!authState.authenticated) {
    res.status(401).json({
      error: {
        message: `Provider not authenticated: ${authState.message}`,
        type: "authentication_error",
      },
    });
    return;
  }

  const completionId = `chatcmpl-${randomUUID().slice(0, 12)}`;
  const created = Math.floor(Date.now() / 1000);

  // --- Streaming ---
  if (stream) {
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache");
    res.setHeader("Connection", "keep-alive");
    res.flushHeaders();

    let firstChunk = true;

    try {
      const result = await provider.stream(
        messages,
        model,
        (text: string) => {
          const chunk = {
            id: completionId,
            object: "chat.completion.chunk" as const,
            created,
            model: model || "claude-sonnet-4",
            choices: [
              {
                index: 0,
                delta: firstChunk
                  ? { role: "assistant" as const, content: text }
                  : { content: text },
                finish_reason: null,
              },
            ],
          };
          firstChunk = false;
          res.write(`data: ${JSON.stringify(chunk)}\n\n`);
        },
      );

      const stopChunk = {
        id: completionId,
        object: "chat.completion.chunk",
        created,
        model: result.model,
        choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
      };
      res.write(`data: ${JSON.stringify(stopChunk)}\n\n`);
      res.write("data: [DONE]\n\n");
      res.end();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      res.write(
        `data: ${JSON.stringify({ error: { message, type: "server_error" } })}\n\n`,
      );
      res.end();
    }

    return;
  }

  // --- Non-streaming ---
  try {
    const result = await provider.complete(messages, model);

    const promptChars = messages.reduce((s, m) => s + m.content.length, 0);
    const promptTokens = Math.ceil(promptChars / 4);
    const completionTokens = Math.ceil(result.content.length / 4);

    res.json({
      id: completionId,
      object: "chat.completion",
      created,
      model: result.model,
      choices: [
        {
          index: 0,
          message: { role: "assistant", content: result.content },
          finish_reason: "stop",
        },
      ],
      usage: {
        prompt_tokens: promptTokens,
        completion_tokens: completionTokens,
        total_tokens: promptTokens + completionTokens,
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    const status = message.includes("not authenticated") ? 401 : 500;
    res.status(status).json({
      error: { message, type: "server_error" },
    });
  }
});

// --- Start ---

app.listen(PORT, BIND_HOST, () => {
  console.log(`AI Sidecar listening on ${BIND_HOST}:${PORT}`);
  if (!SIDECAR_API_KEY) {
    console.warn("WARNING: SIDECAR_API_KEY not set. Endpoints are unauthenticated.");
  }
});

export { app };
