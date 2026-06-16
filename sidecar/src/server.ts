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
 *
 * Every endpoint except /health requires `Authorization: Bearer $SIDECAR_API_KEY`.
 * The server refuses to start without a key unless SIDECAR_ALLOW_UNAUTHENTICATED=true
 * is set explicitly (isolated local development only).
 */

// Sentry must be imported before express/http so it can instrument them; no-op
// unless GLYCEMICGPT_SIDECAR_SENTRY_DSN is set.
import "./instrument.js";
import * as Sentry from "@sentry/node";
import { isSentryEnabled } from "./observability.js";

import express from "express";
import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { healthHandler } from "./health.js";
import { authRouter } from "./auth/oauth-server.js";
import { claude, codex, anthropicVision } from "./providers/index.js";
import {
  InvalidImageError,
  parseImageDataUrl,
  VisionUnavailableError,
  VISION_UNAVAILABLE_MESSAGE,
} from "./providers/image-utils.js";
import type {
  ChatMessage,
  MultimodalMessage,
  VisionRunner,
} from "./providers/types.js";

const app = express();
const PORT = parseInt(process.env.SIDECAR_PORT || "3456", 10);
const BIND_HOST = process.env.SIDECAR_BIND_HOST || "0.0.0.0";
const SIDECAR_API_KEY = process.env.SIDECAR_API_KEY || "";
// Explicit opt-out for isolated local development only. Without a key the
// AI proxy and token-store write/revoke endpoints accept any caller, so an
// empty key must never be a silent default -- startup fails without this flag.
const ALLOW_UNAUTHENTICATED = process.env.SIDECAR_ALLOW_UNAUTHENTICATED === "true";
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || "http://localhost:3000")
  .split(",")
  .map((o) => o.trim())
  .filter((o) => o && o !== "*"); // Reject wildcards
// The chat endpoint carries images (base64 meal photos), so it needs a larger
// body limit. Because text and image requests share /v1/chat/completions, the
// whole chat route accepts up to this limit; only the /auth (and other) routes
// keep the original tight 256kb cap. A client-resized image is typically well
// under 1 MB; the default leaves headroom for a couple of images. Configurable
// so deployments can tighten it.
const JSON_BODY_LIMIT = process.env.SIDECAR_MAX_BODY_SIZE || "8mb";
/** Upper bound on requested completion tokens (clamps client-supplied values). */
const MAX_COMPLETION_TOKENS = 4096;
const parseJsonStandard = express.json({ limit: "256kb" });
const parseJsonVision = express.json({ limit: JSON_BODY_LIMIT });

// --- Middleware ---
// Body parsing is mounted per-route rather than globally so only the vision
// endpoint carries the larger limit.

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
    res.setHeader("Vary", "Origin");
    // nosemgrep: javascript.express.security.cors-misconfiguration.cors-misconfiguration -- origin validated against ALLOWED_ORIGINS whitelist
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

/** Constant-time string comparison; hashing both sides equalizes lengths. */
function safeEqual(a: string, b: string): boolean {
  const digestA = createHash("sha256").update(a).digest();
  const digestB = createHash("sha256").update(b).digest();
  return timingSafeEqual(digestA, digestB);
}

// Bearer token authentication (skip /health for Docker healthchecks)
app.use((req, res, next) => {
  if (req.path === "/health") return next();

  if (SIDECAR_API_KEY) {
    const auth = req.headers.authorization;
    if (!auth || !safeEqual(auth, `Bearer ${SIDECAR_API_KEY}`)) {
      res.status(401).json({
        error: { message: "Unauthorized", type: "authentication_error" },
      });
      return;
    }
  }
  next();
});

/** True when a model name selects the Codex/OpenAI provider. */
function isCodexModel(model?: string): boolean {
  if (!model) return false;
  const lower = model.toLowerCase();
  // Provider-selection heuristic: gpt-*, codex, and o3 names route to the Codex
  // CLI (which then picks the account-appropriate model itself; we don't forward
  // a model name). No o1 alias is supported.
  return lower.includes("gpt") || lower.includes("codex") || lower.includes("o3");
}

/** Choose the text provider based on model name */
function getProvider(model?: string) {
  return isCodexModel(model) ? codex : claude;
}

/**
 * Choose the vision runner for the active provider, by its sanctioned
 * mechanism. Codex/ChatGPT models use the Codex CLI; Claude models prefer the
 * Anthropic API-key path and fall back to the Claude subscription CLI. Returns
 * null when the selected provider has no configured vision mechanism.
 */
function selectVisionRunner(model?: string): VisionRunner | null {
  if (isCodexModel(model)) {
    return codex.supportsVision() ? codex : null;
  }
  if (anthropicVision.supportsVision()) return anthropicVision; // Anthropic API key
  if (claude.supportsVision()) return claude; // Claude subscription CLI
  return null;
}

type MessageValidation =
  | { valid: true; data: MultimodalMessage[]; hasImages: boolean }
  | { valid: false; error: string };

/**
 * Validate the messages array. Content may be a plain string (the existing
 * text path) or an OpenAI-style array of `text` / `image_url` parts (vision).
 * `hasImages` is true when any message carries an image part.
 */
function validateMessages(messages: unknown): MessageValidation {
  if (!Array.isArray(messages) || messages.length === 0) {
    return { valid: false, error: "messages is required and must be a non-empty array" };
  }
  const validRoles = new Set(["system", "user", "assistant"]);
  let hasImages = false;

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (!msg || typeof msg !== "object") {
      return { valid: false, error: `messages[${i}] must be an object` };
    }
    if (!validRoles.has(msg.role)) {
      return { valid: false, error: `messages[${i}].role must be system, user, or assistant` };
    }

    const content = msg.content;
    if (typeof content === "string") continue;

    if (!Array.isArray(content)) {
      return {
        valid: false,
        error: `messages[${i}].content must be a string or an array of content parts`,
      };
    }
    if (content.length === 0) {
      return { valid: false, error: `messages[${i}].content must not be empty` };
    }
    for (let j = 0; j < content.length; j++) {
      const part = content[j];
      if (!part || typeof part !== "object") {
        return { valid: false, error: `messages[${i}].content[${j}] must be an object` };
      }
      if (part.type === "text") {
        if (typeof part.text !== "string") {
          return { valid: false, error: `messages[${i}].content[${j}].text must be a string` };
        }
      } else if (part.type === "image_url") {
        if (!part.image_url || typeof part.image_url.url !== "string") {
          return {
            valid: false,
            error: `messages[${i}].content[${j}].image_url.url must be a string`,
          };
        }
        // Images are only meaningful on the user turn: the vision providers
        // drop or collapse images on system/assistant roles, so an accepted
        // request would change meaning by runner. Reject them here.
        if (msg.role !== "user") {
          return {
            valid: false,
            error: `messages[${i}].content[${j}]: images are only allowed on a user message`,
          };
        }
        // Validate the data URL at the request boundary so a malformed image is
        // always a 400, independent of which provider (or none) is configured.
        try {
          parseImageDataUrl(part.image_url.url);
        } catch (err) {
          if (err instanceof InvalidImageError) {
            return { valid: false, error: err.message };
          }
          throw err;
        }
        hasImages = true;
      } else {
        return {
          valid: false,
          error: `messages[${i}].content[${j}].type must be "text" or "image_url"`,
        };
      }
    }
  }

  return { valid: true, data: messages as MultimodalMessage[], hasImages };
}

/** Flatten multimodal messages to text-only for the CLI provider path. */
function flattenToText(messages: MultimodalMessage[]): ChatMessage[] {
  return messages.map((m) => ({
    role: m.role,
    content:
      typeof m.content === "string"
        ? m.content
        : m.content
            .filter((p): p is { type: "text"; text: string } => p.type === "text")
            .map((p) => p.text)
            .join("\n"),
  }));
}

// --- Routes ---

app.get("/health", healthHandler);

app.use("/auth", parseJsonStandard, authRouter);

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

interface VisionRequestContext {
  model?: string;
  maxTokens?: number;
  stream: boolean;
  completionId: string;
  created: number;
}

/**
 * Handle an image-bearing chat request by routing to the active provider's
 * sanctioned vision mechanism (Anthropic API key, Claude/ChatGPT subscription
 * CLI). Maps provider errors to stable OpenAI-shaped responses, including the
 * "vision unavailable on your provider" fallback contract (HTTP 422,
 * `type: "vision_unavailable"`).
 */
async function handleVision(
  res: express.Response,
  messages: MultimodalMessage[],
  ctx: VisionRequestContext,
): Promise<void> {
  // Select the vision runner for the active provider; short-circuit with the
  // fallback contract when no provider has a configured vision mechanism.
  const runner = selectVisionRunner(ctx.model);
  if (!runner) {
    res.status(422).json({
      error: {
        message: VISION_UNAVAILABLE_MESSAGE,
        type: "vision_unavailable",
        code: "vision_unavailable",
      },
    });
    return;
  }

  try {
    const result = await runner.completeVision(messages, {
      model: ctx.model,
      maxTokens: ctx.maxTokens,
    });

    // --- Streaming: the vision path (direct Messages API) is non-streaming, so
    // there is no token-by-token streaming for image requests. When a caller
    // asks for stream:true we satisfy the OpenAI SSE contract by emitting the
    // already-complete result as a single content chunk. ---
    if (ctx.stream) {
      res.setHeader("Content-Type", "text/event-stream");
      res.setHeader("Cache-Control", "no-cache");
      res.setHeader("Connection", "keep-alive");
      res.flushHeaders();
      res.write(
        `data: ${JSON.stringify({
          id: ctx.completionId,
          object: "chat.completion.chunk",
          created: ctx.created,
          model: result.model,
          choices: [
            {
              index: 0,
              delta: { role: "assistant", content: result.content },
              finish_reason: null,
            },
          ],
        })}\n\n`,
      );
      res.write(
        `data: ${JSON.stringify({
          id: ctx.completionId,
          object: "chat.completion.chunk",
          created: ctx.created,
          model: result.model,
          choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
        })}\n\n`,
      );
      res.write("data: [DONE]\n\n");
      res.end();
      return;
    }

    // Token usage estimate counts text only — image tokens are not modeled here.
    const promptChars = messages.reduce((s, m) => {
      if (typeof m.content === "string") return s + m.content.length;
      return (
        s +
        m.content.reduce((c, p) => c + (p.type === "text" ? p.text.length : 0), 0)
      );
    }, 0);
    const promptTokens = Math.ceil(promptChars / 4);
    const completionTokens = Math.ceil(result.content.length / 4);

    res.json({
      id: ctx.completionId,
      object: "chat.completion",
      created: ctx.created,
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
    if (err instanceof VisionUnavailableError) {
      res.status(422).json({
        error: {
          message: err.message,
          type: "vision_unavailable",
          code: "vision_unavailable",
        },
      });
      return;
    }
    if (err instanceof InvalidImageError) {
      res.status(400).json({
        error: { message: err.message, type: "invalid_request_error" },
      });
      return;
    }
    Sentry.captureException(err);
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: { message, type: "server_error" } });
  }
}

/** POST /v1/chat/completions - OpenAI-compatible chat */
app.post("/v1/chat/completions", parseJsonVision, async (req, res) => {
  const body = req.body as Record<string, unknown>;

  // Runtime validation
  const validation = validateMessages(body?.messages);
  if (!validation.valid) {
    res.status(400).json({
      error: { message: validation.error, type: "invalid_request_error" },
    });
    return;
  }
  const model = typeof body.model === "string" ? body.model : undefined;
  const stream = body.stream === true;
  // Clamp a client-supplied max_tokens to a sane range so it cannot drive cost
  // (or trip the upstream API with a non-positive value).
  const maxTokens =
    typeof body.max_tokens === "number" && body.max_tokens > 0
      ? Math.max(1, Math.min(Math.floor(body.max_tokens), MAX_COMPLETION_TOKENS))
      : undefined;

  const completionId = `chatcmpl-${randomUUID().slice(0, 12)}`;
  const created = Math.floor(Date.now() / 1000);

  // Any request carrying an image routes to the direct Messages API vision
  // provider; the CLI text providers cannot accept an inline image.
  if (validation.hasImages) {
    await handleVision(res, validation.data, {
      model,
      maxTokens,
      stream,
      completionId,
      created,
    });
    return;
  }

  // --- Text path (unchanged behavior) ---
  const messages = flattenToText(validation.data);
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
      Sentry.captureException(err);
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
    if (status === 500) Sentry.captureException(err);
    res.status(status).json({
      error: { message, type: "server_error" },
    });
  }
});

// Capture errors that propagate to Express (registered after the routes).
// No-op when Sentry is disabled (no DSN).
if (isSentryEnabled()) {
  Sentry.setupExpressErrorHandler(app);
}

// --- Start ---

// Only start listening when executed directly (node dist/server.js); tests
// import { app } and must not bind a socket or trip the startup guard.
// realpath both sides: Node resolves symlinks in import.meta.url for the ESM
// entry but leaves process.argv[1] as given.
const isMainModule = (() => {
  if (process.argv[1] === undefined) return false;
  try {
    return import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href;
  } catch {
    return false;
  }
})();

if (isMainModule) {
  if (!SIDECAR_API_KEY && !ALLOW_UNAUTHENTICATED) {
    console.error(
      "FATAL: SIDECAR_API_KEY is not set. Generate one with `openssl rand -hex 32` " +
        "and set it for both the sidecar (SIDECAR_API_KEY) and the API (AI_SIDECAR_API_KEY). " +
        "For isolated local development only, set SIDECAR_ALLOW_UNAUTHENTICATED=true to " +
        "run without authentication.",
    );
    process.exit(1);
  }

  app.listen(PORT, BIND_HOST, () => {
    console.log(`AI Sidecar listening on ${BIND_HOST}:${PORT}`);
    if (!SIDECAR_API_KEY) {
      console.warn(
        "WARNING: running unauthenticated (SIDECAR_ALLOW_UNAUTHENTICATED=true). " +
          "All endpoints accept any caller.",
      );
    }
  });
}

export { app };
