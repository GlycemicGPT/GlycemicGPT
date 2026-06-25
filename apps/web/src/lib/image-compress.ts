/**
 * Client-side meal-photo compression, mirroring the mobile `ImageCompressor`:
 * downscale so the longest edge is <= 1280px, re-encode to JPEG, and step the
 * quality down (90 -> 40) until the result is under the server's 5 MiB cap.
 *
 * Re-encoding through a canvas also strips EXIF/GPS metadata (defence in depth
 * on top of the server's EXIF stripping) while `imageOrientation: "from-image"`
 * bakes the EXIF rotation into the pixels so the upload is upright.
 */

const MAX_DIMENSION = 1280;
const MAX_BYTES = 5 * 1024 * 1024; // 5 MiB -- matches the API's food_image_max_bytes.
const QUALITY_LADDER = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4];
const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];

/** A user-actionable failure while preparing a photo for upload. */
export class ImageCompressionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ImageCompressionError";
  }
}

/** Fit (w, h) within a square of `max`, preserving aspect ratio. */
function fitWithin(
  width: number,
  height: number,
  max: number
): { width: number; height: number } {
  const longest = Math.max(width, height);
  if (longest <= max) return { width, height };
  const scale = max / longest;
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality: number
): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

/**
 * Validate, downscale, and JPEG-compress a picked image to an upload-ready blob.
 * Throws `ImageCompressionError` with a user-facing message on any failure.
 */
export async function compressImageToJpeg(file: File): Promise<Blob> {
  if (file.type && !ACCEPTED_TYPES.includes(file.type)) {
    throw new ImageCompressionError("Use a JPEG, PNG, or WebP photo.");
  }

  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new ImageCompressionError("Couldn't read that photo. Try another one.");
  }

  try {
    const { width, height } = fitWithin(
      bitmap.width,
      bitmap.height,
      MAX_DIMENSION
    );
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      throw new ImageCompressionError("Couldn't process that photo.");
    }
    ctx.drawImage(bitmap, 0, 0, width, height);

    for (const quality of QUALITY_LADDER) {
      const blob = await canvasToBlob(canvas, "image/jpeg", quality);
      if (blob && blob.size <= MAX_BYTES) {
        return blob;
      }
    }
    throw new ImageCompressionError(
      "That photo is too large to upload. Try a smaller one."
    );
  } finally {
    bitmap.close?.();
  }
}
