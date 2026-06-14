/**
 * Direct Anthropic Messages API vision provider (API-key path).
 *
 * Used when an Anthropic API key (`ANTHROPIC_API_KEY`) is configured: the
 * Messages API natively accepts base64 `image` content blocks, authenticated
 * with `x-api-key`. This is the sanctioned mechanism for the "Claude / Anthropic
 * API key" provider mode.
 *
 * This provider does NOT use a Claude subscription OAuth token. Subscription
 * vision goes through the official `claude` CLI (see claude.ts) — sending a
 * subscription Bearer token to the raw Messages API is client impersonation
 * against an enforcement gate and is not a sanctioned path.
 *
 * Security posture: only base64 `data:` image URLs are accepted (enforced in
 * image-utils.ts) — no remote fetch, so no SSRF.
 */

import {
  InvalidImageError,
  MAX_IMAGES,
  parseImageDataUrl,
  VisionUnavailableError,
} from "./image-utils.js";
import type {
  ContentPart,
  MultimodalMessage,
  ProviderResult,
  VisionCompleteOptions,
  VisionRunner,
} from "./types.js";

const ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION = "2023-06-01";

/** Request timeout (2 minutes), matching the CLI providers. */
const REQUEST_TIMEOUT_MS = 120_000;
/** Retry budget for transient (429 / 5xx) responses. */
const MAX_ATTEMPTS = 4;
const BASE_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 8_000;

const DEFAULT_MAX_TOKENS = 1024;

/**
 * Allowlist of caller-facing model names to concrete Anthropic model IDs.
 * Mirrors claude.ts's strict mapping so arbitrary model strings never reach the
 * API.
 */
const VISION_MODEL_MAP: Record<string, string> = {
  "claude-sonnet-4": "claude-sonnet-4-5-20250929",
  "claude-sonnet-4-5": "claude-sonnet-4-5-20250929",
  "claude-sonnet-4-5-20250929": "claude-sonnet-4-5-20250929",
  "claude-opus-4": "claude-opus-4-1-20250805",
  "claude-opus-4-1": "claude-opus-4-1-20250805",
  "claude-haiku-4": "claude-haiku-4-5-20251001",
  "claude-haiku-4-5": "claude-haiku-4-5-20251001",
};
const DEFAULT_VISION_MODEL = "claude-sonnet-4-5-20250929";

/** True when an Anthropic API key is configured. */
export function hasAnthropicApiKey(): boolean {
  return !!process.env.ANTHROPIC_API_KEY?.trim();
}

function resolveVisionModel(model?: string): string {
  if (!model) return DEFAULT_VISION_MODEL;
  return VISION_MODEL_MAP[model] ?? DEFAULT_VISION_MODEL;
}

interface AnthropicImageSource {
  type: "base64";
  media_type: string;
  data: string;
}

type AnthropicContentBlock =
  | { type: "text"; text: string }
  | { type: "image"; source: AnthropicImageSource };

interface AnthropicMessage {
  role: "user" | "assistant";
  content: AnthropicContentBlock[];
}

function partsToText(parts: ContentPart[]): string {
  return parts
    .filter((p): p is ContentPart & { type: "text" } => p.type === "text")
    .map((p) => p.text)
    .join("\n");
}

/** Translate OpenAI-style multimodal messages into the Anthropic request shape. */
function toAnthropicRequest(messages: MultimodalMessage[]): {
  systemTexts: string[];
  anthropicMessages: AnthropicMessage[];
} {
  const systemTexts: string[] = [];
  const anthropicMessages: AnthropicMessage[] = [];
  let imageCount = 0;

  for (const message of messages) {
    if (message.role === "system") {
      const text =
        typeof message.content === "string"
          ? message.content
          : partsToText(message.content);
      if (text.trim()) systemTexts.push(text);
      continue;
    }

    const blocks: AnthropicContentBlock[] = [];
    if (typeof message.content === "string") {
      blocks.push({ type: "text", text: message.content });
    } else {
      for (const part of message.content) {
        if (part.type === "text") {
          blocks.push({ type: "text", text: part.text });
        } else {
          imageCount += 1;
          if (imageCount > MAX_IMAGES) {
            throw new InvalidImageError(`too many images (max ${MAX_IMAGES} per request)`);
          }
          const img = parseImageDataUrl(part.image_url.url);
          blocks.push({
            type: "image",
            source: { type: "base64", media_type: img.mediaType, data: img.data },
          });
        }
      }
    }
    // The Messages API requires alternating user/assistant turns. OpenAI allows
    // consecutive same-role messages, so merge them into the previous turn
    // rather than emitting a non-alternating sequence (which the API rejects
    // with a 400, surfacing as a generic 500 here).
    const last = anthropicMessages[anthropicMessages.length - 1];
    if (last && last.role === message.role) {
      last.content.push(...blocks);
    } else {
      anthropicMessages.push({ role: message.role, content: blocks });
    }
  }

  return { systemTexts, anthropicMessages };
}

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

interface AnthropicResponse {
  content?: Array<{ type: string; text?: string }>;
  model?: string;
  type?: string;
  error?: { type?: string; message?: string };
}

async function postWithRetry(
  body: unknown,
  headers: Record<string, string>,
): Promise<AnthropicResponse> {
  let backoff = BASE_BACKOFF_MS;
  let lastStatus = 0;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const res = await fetch(ANTHROPIC_API_URL, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      lastStatus = res.status;

      if ((res.status === 429 || res.status >= 500) && attempt < MAX_ATTEMPTS) {
        if (res.body) {
          await res.body.cancel().catch(() => {});
        }
        await sleep(backoff);
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
        continue;
      }

      const json = (await res.json().catch(() => ({}))) as AnthropicResponse;
      if (!res.ok) {
        throw new Error(`Anthropic vision request failed (HTTP ${res.status})`);
      }
      return json;
    } catch (err) {
      // A timeout is terminal: retrying a POST that may have produced a
      // completion would risk a duplicate (billed) generation.
      if (err instanceof Error && err.name === "AbortError") {
        throw new Error("Anthropic vision request timed out");
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  throw new Error(`Anthropic vision request failed (HTTP ${lastStatus})`);
}

export class AnthropicVisionProvider implements VisionRunner {
  /** True when this provider can serve a vision request (API key present). */
  supportsVision(): boolean {
    return hasAnthropicApiKey();
  }

  async completeVision(
    messages: MultimodalMessage[],
    options: VisionCompleteOptions = {},
  ): Promise<ProviderResult> {
    const apiKey = process.env.ANTHROPIC_API_KEY?.trim();
    if (!apiKey) {
      throw new VisionUnavailableError();
    }

    const { systemTexts, anthropicMessages } = toAnthropicRequest(messages);
    const model = resolveVisionModel(options.model);
    const body: Record<string, unknown> = {
      model,
      max_tokens: options.maxTokens ?? DEFAULT_MAX_TOKENS,
      messages: anthropicMessages,
    };
    if (systemTexts.length > 0) {
      body.system = systemTexts.map((text) => ({ type: "text", text }));
    }

    const headers: Record<string, string> = {
      "content-type": "application/json",
      "anthropic-version": ANTHROPIC_VERSION,
      "x-api-key": apiKey,
    };

    const json = await postWithRetry(body, headers);
    if (json.error) {
      throw new Error("Anthropic vision request returned an error");
    }
    const content = (json.content ?? [])
      .filter((b) => b.type === "text" && typeof b.text === "string")
      .map((b) => b.text as string)
      .join("");

    return { content, model: json.model ?? model };
  }
}
