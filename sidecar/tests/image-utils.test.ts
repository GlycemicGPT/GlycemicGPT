/**
 * Tests for the shared image-handling utilities (the SSRF/validation surface
 * used by every vision provider).
 */

import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import {
  flattenVisionRequest,
  InvalidImageError,
  MAX_IMAGES,
  parseImageDataUrl,
  writeImagesToTempDir,
} from "../src/providers/image-utils.js";
import type { MultimodalMessage } from "../src/providers/types.js";

const PNG_1x1 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWqM7HQAAAABJRU5ErkJggg==";
const PNG_DATA_URL = `data:image/png;base64,${PNG_1x1}`;

describe("parseImageDataUrl", () => {
  it("parses a valid base64 data URL", () => {
    const img = parseImageDataUrl(PNG_DATA_URL);
    expect(img.mediaType).toBe("image/png");
    expect(img.data).toBe(PNG_1x1);
  });

  it("rejects remote http(s) URLs (no fetch)", () => {
    expect(() => parseImageDataUrl("https://evil.example/x.png")).toThrow(InvalidImageError);
  });

  it("rejects file:// URLs", () => {
    expect(() => parseImageDataUrl("file:///etc/passwd")).toThrow(InvalidImageError);
  });

  it("rejects unsupported media types", () => {
    expect(() => parseImageDataUrl("data:image/svg+xml;base64,PHN2Zz4=")).toThrow(
      InvalidImageError,
    );
  });

  it("rejects non-base64 data URLs", () => {
    expect(() => parseImageDataUrl("data:image/png,not-base64")).toThrow(InvalidImageError);
  });

  it("rejects non-base64 characters in the payload", () => {
    expect(() => parseImageDataUrl("data:image/png;base64,@@@not-valid@@@")).toThrow(
      InvalidImageError,
    );
  });

  it("rejects non-canonical base64 (bad quartet length)", () => {
    // "abc" is alphabet-valid but length 3 (not a multiple of 4).
    expect(() => parseImageDataUrl("data:image/png;base64,abc")).toThrow(InvalidImageError);
  });

  it("rejects base64 with misplaced padding", () => {
    expect(() => parseImageDataUrl("data:image/png;base64,a=bc")).toThrow(InvalidImageError);
  });
});

describe("flattenVisionRequest", () => {
  it("splits system text, user text, and images", () => {
    const messages: MultimodalMessage[] = [
      { role: "system", content: "Describe the food." },
      {
        role: "user",
        content: [
          { type: "image_url", image_url: { url: PNG_DATA_URL } },
          { type: "text", text: "Estimate the carbs." },
        ],
      },
    ];
    const out = flattenVisionRequest(messages);
    expect(out.systemText).toBe("Describe the food.");
    expect(out.userText).toBe("Estimate the carbs.");
    expect(out.images).toHaveLength(1);
    expect(out.images[0].mediaType).toBe("image/png");
  });

  it("handles string content on both roles", () => {
    const out = flattenVisionRequest([
      { role: "system", content: "sys" },
      { role: "user", content: "hi" },
    ]);
    expect(out.systemText).toBe("sys");
    expect(out.userText).toBe("hi");
    expect(out.images).toEqual([]);
  });

  it("rejects more images than the per-request cap", () => {
    const parts = Array.from({ length: MAX_IMAGES + 1 }, () => ({
      type: "image_url" as const,
      image_url: { url: PNG_DATA_URL },
    }));
    expect(() => flattenVisionRequest([{ role: "user", content: parts }])).toThrow(
      InvalidImageError,
    );
  });

  it("propagates a bad image URL", () => {
    const messages: MultimodalMessage[] = [
      {
        role: "user",
        content: [{ type: "image_url", image_url: { url: "https://evil.example/x.png" } }],
      },
    ];
    expect(() => flattenVisionRequest(messages)).toThrow(InvalidImageError);
  });
});

describe("writeImagesToTempDir", () => {
  it("writes images to disk and cleans them up", () => {
    const temp = writeImagesToTempDir([{ mediaType: "image/png", data: PNG_1x1 }]);
    try {
      expect(temp.paths).toHaveLength(1);
      expect(temp.paths[0]).toMatch(/image-0\.png$/);
      expect(existsSync(temp.paths[0])).toBe(true);
      // The written bytes decode from the base64 we passed in.
      expect(readFileSync(temp.paths[0]).equals(Buffer.from(PNG_1x1, "base64"))).toBe(true);
    } finally {
      temp.cleanup();
    }
    expect(existsSync(temp.dir)).toBe(false);
  });
});
