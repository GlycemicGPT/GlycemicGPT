"use client";

import { Suspense } from "react";
import { Loader2 } from "lucide-react";
import { NightscoutOnboardingWizard } from "@/components/integrations/nightscout-onboarding-wizard";

// Bookmark/refresh-resilient route for the smart-onboarding wizard.
// Step 4 (first sync) can take ~20s, so this is a real route rather
// than a modal -- losing the wizard mid-sync to an accidental Esc
// or click-outside would be bad UX.
//
// The wizard calls `useSearchParams()` to support the `?connection=<id>`
// re-import deep link (Story 43.7d). Next 15 requires that consumer
// to be inside a Suspense boundary; the fallback below is what the
// page shows during the static-shell render.
export default function NightscoutConnectPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
          <Loader2 className="h-6 w-6 text-blue-500 animate-spin" />
        </div>
      }
    >
      <NightscoutOnboardingWizard />
    </Suspense>
  );
}
