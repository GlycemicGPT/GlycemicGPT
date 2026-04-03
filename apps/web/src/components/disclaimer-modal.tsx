"use client";

/**
 * Safety Disclaimer Modal Component.
 *
 * Story 1.3: First-Run Safety Disclaimer
 * FR50: System can display experimental software disclaimer on first use
 * FR51: User must acknowledge disclaimer before using system
 */

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  FlaskConical,
  Brain,
  ShieldOff,
  Stethoscope,
  AlertTriangle,
  Check,
} from "lucide-react";
import {
  acknowledgeDisclaimer,
  getDisclaimerStatus,
  getDisclaimerContent,
  type DisclaimerContent,
} from "@/lib/api";
import { getSessionId } from "@/lib/session";

interface DisclaimerModalProps {
  onAcknowledge?: () => void;
}

const iconMap: Record<string, React.ComponentType<{ className?: string }>> = {
  flask: FlaskConical,
  brain: Brain,
  "shield-x": ShieldOff,
  stethoscope: Stethoscope,
};

export function DisclaimerModal({ onAcknowledge }: DisclaimerModalProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [content, setContent] = useState<DisclaimerContent | null>(null);
  const [checkboxes, setCheckboxes] = useState<Record<string, boolean>>({});

  useEffect(() => {
    async function checkStatus() {
      const sessionId = getSessionId();
      if (!sessionId) {
        setIsLoading(false);
        return;
      }

      try {
        const [status, disclaimerContent] = await Promise.all([
          getDisclaimerStatus(sessionId),
          getDisclaimerContent(),
        ]);

        setContent(disclaimerContent);

        // Initialize checkbox state
        const initialCheckboxes: Record<string, boolean> = {};
        disclaimerContent.checkboxes.forEach((cb) => {
          initialCheckboxes[cb.id] = false;
        });
        setCheckboxes(initialCheckboxes);

        if (!status.acknowledged) {
          setIsOpen(true);
        }
      } catch {
        // On error, show the disclaimer to be safe
        try {
          const disclaimerContent = await getDisclaimerContent();
          setContent(disclaimerContent);
          const initialCheckboxes: Record<string, boolean> = {};
          disclaimerContent.checkboxes.forEach((cb) => {
            initialCheckboxes[cb.id] = false;
          });
          setCheckboxes(initialCheckboxes);
          setIsOpen(true);
        } catch {
          // If we can't even get content, use fallback
          setContent(null);
          setIsOpen(true);
        }
      } finally {
        setIsLoading(false);
      }
    }

    checkStatus();
  }, []);

  const handleCheckboxChange = (id: string) => {
    setCheckboxes((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
    setError(null);
  };

  const allChecked = Object.values(checkboxes).every(Boolean);

  const handleAccept = async () => {
    if (!allChecked) {
      setError("Please check both acknowledgment boxes to continue");
      return;
    }

    const sessionId = getSessionId();
    if (!sessionId) {
      setError("Session error. Please refresh the page.");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await acknowledgeDisclaimer({
        session_id: sessionId,
        checkbox_experimental: checkboxes.checkbox_experimental ?? false,
        checkbox_not_medical_advice:
          checkboxes.checkbox_not_medical_advice ?? false,
      });

      setIsOpen(false);
      onAcknowledge?.();
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

  // Don't render anything while loading
  if (isLoading) {
    return null;
  }

  // Fallback content if API fails
  const displayContent: DisclaimerContent = content ?? {
    version: "1.0",
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
        icon: "shield-x",
        title: "Not FDA Approved",
        text: "This software is not FDA approved for medical use. It is not intended to diagnose, treat, cure, or prevent any disease.",
      },
      {
        icon: "stethoscope",
        title: "Consult Your Healthcare Provider",
        text: "Always consult your healthcare provider before making any changes to your diabetes management regimen.",
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
    ],
    button_text: "I Understand & Accept",
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", duration: 0.5 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
          >
            <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto shadow-2xl">
              {/* Header */}
              <div className="p-6 border-b border-slate-700">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-amber-500/20 rounded-lg">
                    <AlertTriangle className="w-6 h-6 text-amber-500" />
                  </div>
                  <h2 className="text-xl font-semibold text-white">
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
                      <div className="flex-shrink-0">
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
                        flex-shrink-0 w-5 h-5 mt-0.5 rounded border-2 transition-all
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
                    <span className="text-sm text-gray-300">
                      {checkbox.label}
                    </span>
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
        </>
      )}
    </AnimatePresence>
  );
}
