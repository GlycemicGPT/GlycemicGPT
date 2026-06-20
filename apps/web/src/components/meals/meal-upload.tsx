"use client";

/**
 * Web meal-photo upload: pick -> validate/compress -> POST multipart.
 *
 * Mirrors the mobile compress-then-multipart flow (1280px / quality ladder /
 * 5 MiB JPEG). On a vision-unavailable / no-provider / feature-off response it
 * surfaces the matching dead-end state and NEVER a fabricated estimate.
 */

import { useRef, useState } from "react";
import { Camera, Loader2 } from "lucide-react";
import { uploadFoodRecord, type FoodRecord } from "@/lib/api";
import { compressImageToJpeg, ImageCompressionError } from "@/lib/image-compress";
import { classifyMealError, type MealErrorInfo } from "@/lib/meal-errors";
import { MealErrorPanel } from "@/components/meals/meal-ui";

const ACCEPT = "image/jpeg,image/png,image/webp";

export function MealUpload({
  onUploaded,
  onFeatureOff,
}: {
  onUploaded: (record: FoodRecord) => void;
  /** Called when an upload reveals the feature is off, so the page can switch state. */
  onFeatureOff?: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [errorInfo, setErrorInfo] = useState<MealErrorInfo | null>(null);

  async function handleFile(file: File) {
    setErrorInfo(null);
    setBusy(true);
    try {
      const blob = await compressImageToJpeg(file);
      const record = await uploadFoodRecord(blob);
      onUploaded(record);
    } catch (err) {
      if (err instanceof ImageCompressionError) {
        setErrorInfo({
          kind: "unsupported_image",
          title: "Couldn't use that photo",
          message: err.message,
          retryable: true,
        });
      } else {
        const info = classifyMealError(err);
        setErrorInfo(info);
        if (info.kind === "feature_off") onFeatureOff?.();
      }
    } finally {
      setBusy(false);
      // Reset so re-picking the same file fires onChange again.
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="space-y-3">
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        data-testid="meal-file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
        }}
      />
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        data-testid="meal-upload-button"
        className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
      >
        {busy ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" data-testid="meal-uploading" />
            Estimating carbs…
          </>
        ) : (
          <>
            <Camera className="h-4 w-4" />
            Log a meal
          </>
        )}
      </button>

      {errorInfo && (
        <MealErrorPanel
          info={errorInfo}
          onDismiss={
            errorInfo.retryable ? () => setErrorInfo(null) : undefined
          }
        />
      )}
    </div>
  );
}
