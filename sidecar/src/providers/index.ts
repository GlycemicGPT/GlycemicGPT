/**
 * Singleton provider instances.
 *
 * All modules that need provider access should import from here
 * to avoid creating duplicate instances.
 */

import { ClaudeProvider } from "./claude.js";
import { CodexProvider } from "./codex.js";
import { AnthropicVisionProvider } from "./anthropic-vision.js";

export const claude = new ClaudeProvider();
export const codex = new CodexProvider();
/** Anthropic API-key vision path (direct Messages API). The Claude/ChatGPT
 * subscription vision paths live on the `claude` / `codex` providers above. */
export const anthropicVision = new AnthropicVisionProvider();
