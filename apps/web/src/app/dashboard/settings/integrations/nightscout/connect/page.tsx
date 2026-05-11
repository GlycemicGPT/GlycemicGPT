"use client";

import { NightscoutOnboardingWizard } from "@/components/integrations/nightscout-onboarding-wizard";

// Bookmark/refresh-resilient route for the smart-onboarding wizard.
// Step 4 (first sync) can take ~20s, so this is a real route rather
// than a modal -- losing the wizard mid-sync to an accidental Esc
// or click-outside would be bad UX.
export default function NightscoutConnectPage() {
  return <NightscoutOnboardingWizard />;
}
