/**
 * Shared image handling for the vision providers.
 *
 * Security posture (used by every vision path): only base64 `data:` image URLs
 * are accepted. Remote (`http(s)://`, `file://`, …) URLs are rejected and never
 * fetched, which keeps the image surface free of SSRF and path traversal. Media
 * type, decoded size, and image count are all bounded.
 */

import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ContentPart, MultimodalMessage } from "./types.js";

/** Cap on images per request — a meal photo needs one or two, not a gallery. */
export const MAX_IMAGES = 4;
/** Reject images above ~5 MB (the Anthropic per-image ceiling) early. */
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export const EXT_BY_MEDIA_TYPE: Record<string, string> = {
  "image/jpeg": ".jpg",
  "image/png": ".png",
  "image/gif": ".gif",
  "image/webp": ".webp",
};
const ALLOWED_MEDIA_TYPES = new Set(Object.keys(EXT_BY_MEDIA_TYPE));

/**
 * Stable user-facing message for the "vision unavailable on your provider"
 * fallback contract. Exported so every surface returns identical copy.
 */
export const VISION_UNAVAILABLE_MESSAGE =
  "Vision is not available on your current AI provider. Configure an API key " +
  "(Anthropic or OpenAI), a Claude or ChatGPT subscription, or a vision-capable " +
  "local model to estimate from a photo.";

/** Thrown when no vision-capable provider/credential is configured. */
export class VisionUnavailableError extends Error {
  constructor(message: string = VISION_UNAVAILABLE_MESSAGE) {
    super(message);
    this.name = "VisionUnavailableError";
  }
}

/** Thrown when an image payload is malformed, oversized, or a disallowed type. */
export class InvalidImageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidImageError";
  }
}

export interface VisionImage {
  /** e.g. "image/png" */
  mediaType: string;
  /** base64-encoded image bytes (no data: prefix) */
  data: string;
}

/**
 * Parse a base64 `data:` image URL. Rejects any non-`data:` scheme so remote
 * content is never fetched.
 */
export function parseImageDataUrl(url: string): VisionImage {
  if (typeof url !== "string" || !url.startsWith("data:")) {
    throw new InvalidImageError(
      "image_url must be a base64 data: URL; remote URLs are not fetched",
    );
  }
  const comma = url.indexOf(",");
  if (comma < 0) {
    throw new InvalidImageError("malformed data URL (no comma separator)");
  }
  const meta = url.slice(5, comma); // e.g. "image/jpeg;base64"
  const data = url.slice(comma + 1);
  if (!/;base64$/i.test(meta)) {
    throw new InvalidImageError("data URL must be base64-encoded");
  }
  const mediaType = meta.slice(0, meta.length - ";base64".length).toLowerCase();
  if (!ALLOWED_MEDIA_TYPES.has(mediaType)) {
    throw new InvalidImageError(`unsupported image media type: ${mediaType}`);
  }
  if (!/^[A-Za-z0-9+/=\s]*$/.test(data)) {
    throw new InvalidImageError("image data is not valid base64");
  }
  const normalized = data.replace(/\s+/g, "");
  // Canonical base64: non-empty, length a multiple of 4, padding only at the
  // end. Catches malformed quartets/padding that the alphabet check alone lets
  // through (they would otherwise surface as a generic upstream 500).
  if (
    normalized.length === 0 ||
    normalized.length % 4 !== 0 ||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(normalized)
  ) {
    throw new InvalidImageError("image data is not canonically base64-encoded");
  }
  // Length is a multiple of 4 (validated above), so the exact decoded byte
  // count is (length / 4) * 3 minus the padding ('=') bytes.
  const padding = normalized.endsWith("==") ? 2 : normalized.endsWith("=") ? 1 : 0;
  if ((normalized.length / 4) * 3 - padding > MAX_IMAGE_BYTES) {
    throw new InvalidImageError("image exceeds the maximum allowed size");
  }
  return { mediaType, data: normalized };
}

export interface FlattenedVisionRequest {
  /** Concatenated system-role text (instructions). */
  systemText: string;
  /** Concatenated user/assistant text (the question). */
  userText: string;
  /** Validated images, in order. */
  images: VisionImage[];
}

/**
 * Flatten OpenAI-style multimodal messages into the parts the CLI vision paths
 * need: system text, user text, and validated images. Enforces {@link MAX_IMAGES}.
 * (The direct Anthropic API path keeps its own structured translation; it shares
 * only {@link parseImageDataUrl}.)
 */
export function flattenVisionRequest(messages: MultimodalMessage[]): FlattenedVisionRequest {
  const systemParts: string[] = [];
  const userParts: string[] = [];
  const images: VisionImage[] = [];

  const pushText = (target: string[], parts: ContentPart[]) => {
    for (const part of parts) {
      if (part.type === "text") {
        target.push(part.text);
      } else {
        if (images.length >= MAX_IMAGES) {
          throw new InvalidImageError(`too many images (max ${MAX_IMAGES} per request)`);
        }
        images.push(parseImageDataUrl(part.image_url.url));
      }
    }
  };

  for (const message of messages) {
    const target = message.role === "system" ? systemParts : userParts;
    if (typeof message.content === "string") {
      target.push(message.content);
    } else {
      pushText(target, message.content);
    }
  }

  return {
    systemText: systemParts.join("\n").trim(),
    userText: userParts.join("\n").trim(),
    images,
  };
}

export interface TempImageSet {
  /** Absolute paths of the written image files. */
  paths: string[];
  /** The temp directory holding them (scope this for the subprocess). */
  dir: string;
  /** Remove the temp directory and its contents. Always call in a finally. */
  cleanup: () => void;
}

/**
 * Write images to a fresh, private temp directory so a CLI vision provider can
 * read them off disk. The directory is the only path the subprocess is granted.
 */
export function writeImagesToTempDir(images: VisionImage[]): TempImageSet {
  const dir = mkdtempSync(join(tmpdir(), "gg-vision-"));
  chmodSync(dir, 0o700); // private to this process, not reliant on umask
  const paths: string[] = [];
  try {
    images.forEach((img, i) => {
      const ext = EXT_BY_MEDIA_TYPE[img.mediaType] ?? ".img";
      const file = join(dir, `image-${i}${ext}`);
      writeFileSync(file, Buffer.from(img.data, "base64"), { mode: 0o600 });
      paths.push(file);
    });
  } catch (err) {
    rmSync(dir, { recursive: true, force: true });
    throw err;
  }
  return {
    paths,
    dir,
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
  };
}
