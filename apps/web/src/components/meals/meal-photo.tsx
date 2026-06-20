"use client";

import { useState, useEffect } from "react";
import { fetchFoodRecordPhotoObjectUrl } from "@/lib/api";
import { MealPhotoPlaceholder } from "@/components/meals/meal-ui";

/**
 * Renders a record's stored meal photo, fetched as a credentialed `blob:` URL
 * (the endpoint is cookie-protected and next/image can't carry the cookie).
 * Shows the neutral placeholder while loading or if the photo can't be loaded
 * (e.g. an older record without a served photo), and revokes the object URL on
 * unmount / id change so blobs aren't leaked.
 */
export function MealPhoto({
  recordId,
  size = "sm",
}: {
  recordId: string;
  size?: "sm" | "lg";
}) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    fetchFoodRecordPhotoObjectUrl(recordId)
      .then((resolved) => {
        if (active) {
          objectUrl = resolved;
          setUrl(resolved);
        } else {
          URL.revokeObjectURL(resolved);
        }
      })
      .catch(() => {
        // Leave the placeholder shown -- no broken-image flash.
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [recordId]);

  if (!url) {
    return <MealPhotoPlaceholder size={size} />;
  }

  const dimensions = size === "lg" ? "h-48 w-full" : "h-14 w-14";
  return (
    // eslint-disable-next-line @next/next/no-img-element -- credentialed blob URL; next/image can't carry the auth cookie.
    <img
      src={url}
      alt="Meal photo"
      data-testid="meal-photo"
      className={`${dimensions} flex-shrink-0 rounded-lg object-cover bg-slate-100 dark:bg-slate-800`}
    />
  );
}
