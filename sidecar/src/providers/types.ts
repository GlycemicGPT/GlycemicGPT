/**
 * Shared types for AI provider subprocess wrappers.
 */

/** OpenAI-compatible chat message */
export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

/** A text segment of an OpenAI-style multimodal message. */
export interface TextContentPart {
  type: "text";
  text: string;
}

/**
 * An image segment of an OpenAI-style multimodal message.
 *
 * Only base64 `data:` URLs are accepted downstream — remote URLs are never
 * fetched server-side (see anthropic-vision.ts), which keeps the image surface
 * free of SSRF.
 */
export interface ImageContentPart {
  type: "image_url";
  image_url: { url: string; detail?: "auto" | "low" | "high" };
}

export type ContentPart = TextContentPart | ImageContentPart;

/** A chat message whose content may be plain text or a mix of text and images. */
export interface MultimodalMessage {
  role: "system" | "user" | "assistant";
  content: string | ContentPart[];
}

/** Options for a vision completion. */
export interface VisionCompleteOptions {
  model?: string;
  maxTokens?: number;
}

/**
 * Something that can answer a prompt containing one or more images via a
 * sanctioned vision mechanism. Each provider mode advertises whether it can do
 * vision and runs it through its own transport: the Anthropic API-key path uses
 * the Messages API; the Claude/ChatGPT subscription paths drive their official
 * CLIs (the CLI renders the image — no credential impersonation).
 */
export interface VisionRunner {
  /** True when this runner can currently serve a vision request. */
  supportsVision(): boolean;
  /** Run a non-streaming multimodal completion. */
  completeVision(
    messages: MultimodalMessage[],
    options?: VisionCompleteOptions,
  ): Promise<ProviderResult>;
}

/** OpenAI-compatible chat completion request (text or multimodal). */
export interface ChatCompletionRequest {
  model?: string;
  messages: MultimodalMessage[];
  stream?: boolean;
  temperature?: number;
  max_tokens?: number;
}

/** OpenAI-compatible non-streaming response */
export interface ChatCompletionResponse {
  id: string;
  object: "chat.completion";
  created: number;
  model: string;
  choices: Array<{
    index: number;
    message: { role: "assistant"; content: string };
    finish_reason: "stop" | "length";
  }>;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

/** OpenAI-compatible streaming chunk */
export interface ChatCompletionChunk {
  id: string;
  object: "chat.completion.chunk";
  created: number;
  model: string;
  choices: Array<{
    index: number;
    delta: { role?: "assistant"; content?: string };
    finish_reason: "stop" | null;
  }>;
}

/** Result from a non-streaming provider call */
export interface ProviderResult {
  content: string;
  model: string;
}

/** Provider authentication state */
export interface ProviderAuthState {
  authenticated: boolean;
  provider: "claude" | "codex";
  /** Human-readable status message */
  message: string;
}

/** Abstract interface that each provider must implement */
export interface AIProvider {
  /** Check if this provider is authenticated and ready */
  checkAuth(): Promise<ProviderAuthState>;

  /** Run a non-streaming chat completion */
  complete(
    messages: ChatMessage[],
    model?: string,
  ): Promise<ProviderResult>;

  /** Run a streaming chat completion, calling onChunk for each text delta */
  stream(
    messages: ChatMessage[],
    model?: string,
    onChunk?: (text: string) => void,
  ): Promise<ProviderResult>;
}
