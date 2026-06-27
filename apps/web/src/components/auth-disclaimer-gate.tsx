"use client";

/**
 * Story 15.5: Auth Disclaimer Gate
 *
 * Blocks dashboard access until the authenticated user acknowledges
 * the safety disclaimer. Wraps children and shows a blocking overlay
 * when user.disclaimer_acknowledged is false.
 */

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  FlaskConical,
  Brain,
  ShieldOff,
  Stethoscope,
  AlertTriangle,
  Camera,
  Check,
  Cloud,
  Loader2,
} from "lucide-react";
import { useUserContext } from "@/providers/user-provider";
import {
  acknowledgeDisclaimerAuth,
  getDisclaimerContent,
  type DisclaimerContent,
} from "@/lib/api";

const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  flask: FlaskConical,
  brain: Brain,
  "shield-x": ShieldOff,
  stethoscope: Stethoscope,
  cloud: Cloud,
  camera: Camera,
};

export function AuthDisclaimerGate({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, isLoading, refreshUser } = useUserContext();
  const [content, setContent] = useState<DisclaimerContent | null>(null);
  const [checkboxes, setCheckboxes] = useState<Record<string, boolean>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contentLoading, setContentLoading] = useState(true);

  const needsDisclaimer = !isLoading && user && !user.disclaimer_acknowledged;

  // Fetch disclaimer content when the gate determines it's needed
  useEffect(() => {
    if (!needsDisclaimer) {
      setContentLoading(false);
      return;
    }

    async function fetchContent() {
      try {
        const disclaimerContent = await getDisclaimerContent();
        setContent(disclaimerContent);
        const initialCheckboxes: Record<string, boolean> = {};
        disclaimerContent.checkboxes.forEach((cb) => {
          initialCheckboxes[cb.id] = false;
        });
        setCheckboxes(initialCheckboxes);
      } catch {
        // Use fallback content on error
        setContent(null);
        setCheckboxes({
          checkbox_experimental: false,
          checkbox_not_medical_advice: false,
          checkbox_ai_data_flow: false,
        });
      } finally {
        setContentLoading(false);
      }
    }

    fetchContent();
  }, [needsDisclaimer]);

  // While user is loading, show a centered spinner (don't flash the modal)
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-950">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    );
  }

  // User acknowledged or no user (will be handled by auth redirect)
  if (!needsDisclaimer) {
    return <>{children}</>;
  }

  // Loading disclaimer content
  if (contentLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-950">
        <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    );
  }

  const handleCheckboxChange = (id: string) => {
    setCheckboxes((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
    setError(null);
  };

  const allChecked =
    Object.keys(checkboxes).length > 0 &&
    Object.values(checkboxes).every(Boolean);

  const handleAccept = async () => {
    if (!allChecked) {
      setError("Please check all acknowledgment boxes to continue");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await acknowledgeDisclaimerAuth();
      await refreshUser();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to save acknowledgment. Please try again."
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Fallback content if API failed. Mirror the server /content payload
  // (src/routers/disclaimer.py) so a fetch failure still shows the current
  // version and the photo-carb warning -- keep this in sync on every bump.
  const displayContent: DisclaimerContent = content ?? {
    version: "1.2",
    title: "Important Safety Information",
    warnings: [
      {
        icon: "flask",
        title: "Experimental Software",
        text: "This is experimental open-source software. It has not been validated for clinical use and may contain bugs or errors.",
      },
      {
        icon: "brain",
        title: "AI Limitations",
        text: "AI can and will make mistakes. All suggestions should be verified with your healthcare provider before acting on them.",
      },
      {
        icon: "camera",
        title: "Photo Carb Estimates Are Guesses",
        text: "If you use the meal-photo feature, the carbohydrate numbers are AI estimates from an image and are frequently wrong -- including misidentifying the food entirely. They are a rough starting point only. Never use a photo carb estimate to calculate an insulin dose or bolus, and always verify carbs yourself before dosing.",
      },
      {
        icon: "shield-x",
        title: "Not FDA Approved",
        text: "This software is not FDA approved for medical use. It is not intended to diagnose, treat, cure, or prevent any disease.",
      },
      {
        icon: "stethoscope",
        title: "Consult Your Healthcare Provider",
        text: "Always consult your healthcare provider before making any changes to your diabetes management regimen.",
      },
      {
        icon: "cloud",
        title: "AI Data Processing",
        text:
          "GlycemicGPT is BYOAI -- you choose the AI provider. If you configure a cloud-hosted AI provider, your glucose, insulin, pump, and therapy data will be transmitted to that provider's servers for analysis, subject to their data-handling policy. If you configure a local AI provider running on your own infrastructure, your data stays on your network. Review your chosen provider's policy before configuring it.",
      },
    ],
    checkboxes: [
      {
        id: "checkbox_experimental",
        label:
          "I understand this is experimental software and that AI suggestions may be incorrect",
      },
      {
        id: "checkbox_not_medical_advice",
        label:
          "I understand this is not medical advice and I will consult my healthcare provider before making any changes",
      },
      {
        id: "checkbox_ai_data_flow",
        label:
          "I understand that configuring a cloud-hosted AI provider transmits my health data to that provider, and that only local AI providers keep my data on my own network",
      },
    ],
    button_text: "I Understand & Accept",
  };

  return (
    <AnimatePresence>
      {/* Backdrop */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/80 backdrop-blur-xs z-50"
      />

      {/* Modal */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        transition={{ type: "spring", duration: 0.5 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
      >
        <div
          className="bg-slate-900 border border-slate-700 rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto shadow-2xl"
          role="dialog"
          aria-modal="true"
          aria-labelledby="disclaimer-title"
        >
          {/* Header */}
          <div className="p-6 border-b border-slate-700">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-amber-500/20 rounded-lg">
                <AlertTriangle className="w-6 h-6 text-amber-500" />
              </div>
              <h2
                id="disclaimer-title"
                className="text-xl font-semibold text-white"
              >
                {displayContent.title}
              </h2>
            </div>
          </div>

          {/* Content */}
          <div className="p-6 space-y-4">
            {displayContent.warnings.map((warning, index) => {
              const Icon = iconMap[warning.icon] || AlertTriangle;
              return (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.1 }}
                  className="flex gap-4 p-4 bg-slate-800/50 rounded-lg border border-slate-700"
                >
                  <div className="shrink-0">
                    <Icon className="w-5 h-5 text-amber-500" />
                  </div>
                  <div>
                    <h3 className="font-medium text-white mb-1">
                      {warning.title}
                    </h3>
                    <p className="text-sm text-gray-400">{warning.text}</p>
                  </div>
                </motion.div>
              );
            })}
          </div>

          {/* Checkboxes */}
          <div className="px-6 pb-4 space-y-3">
            {displayContent.checkboxes.map((checkbox) => (
              <label
                key={checkbox.id}
                className="flex items-start gap-3 cursor-pointer group"
              >
                <div
                  className={`
                    shrink-0 w-5 h-5 mt-0.5 rounded-sm border-2 transition-all
                    flex items-center justify-center
                    ${
                      checkboxes[checkbox.id]
                        ? "bg-blue-600 border-blue-600"
                        : "border-slate-500 group-hover:border-slate-400"
                    }
                  `}
                  onClick={() => handleCheckboxChange(checkbox.id)}
                >
                  {checkboxes[checkbox.id] && (
                    <Check className="w-3 h-3 text-white" />
                  )}
                </div>
                <input
                  type="checkbox"
                  checked={checkboxes[checkbox.id] ?? false}
                  onChange={() => handleCheckboxChange(checkbox.id)}
                  className="sr-only"
                />
                <span className="text-sm text-gray-300">{checkbox.label}</span>
              </label>
            ))}
          </div>

          {/* Error */}
          {error && (
            <div className="px-6 pb-4">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          {/* Footer */}
          <div className="p-6 border-t border-slate-700">
            <button
              onClick={handleAccept}
              disabled={!allChecked || isSubmitting}
              className={`
                w-full py-3 px-4 rounded-lg font-medium transition-all
                ${
                  allChecked && !isSubmitting
                    ? "bg-blue-600 hover:bg-blue-700 text-white"
                    : "bg-slate-700 text-slate-400 cursor-not-allowed"
                }
              `}
            >
              {isSubmitting ? "Saving..." : displayContent.button_text}
            </button>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
