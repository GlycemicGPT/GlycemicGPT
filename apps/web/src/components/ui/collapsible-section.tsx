"use client";

import { useState, useId } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, type LucideIcon } from "lucide-react";
import clsx from "clsx";

interface CollapsibleSectionProps {
  title: string;
  icon?: LucideIcon;
  defaultOpen?: boolean;
  variant?: "section" | "subsection";
  badge?: React.ReactNode;
  children: React.ReactNode;
}

export function CollapsibleSection({
  title,
  icon: Icon,
  defaultOpen = true,
  variant = "section",
  badge,
  children,
}: CollapsibleSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const id = useId();
  const contentId = `${id}-content`;
  const headerId = `${id}-header`;

  const isSection = variant === "section";

  return (
    <div
      className={clsx(
        isSection
          ? "bg-slate-900 rounded-xl border border-slate-800"
          : "bg-slate-800/30 rounded-lg border border-slate-700/50"
      )}
    >
      <button
        id={headerId}
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-controls={contentId}
        className={clsx(
          "flex items-center justify-between w-full text-left",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset",
          isSection
            ? "px-6 py-4 rounded-xl"
            : "px-4 py-3 rounded-lg"
        )}
      >
        <div className="flex items-center gap-3">
          {Icon && (
            <div
              className={clsx(
                "p-2 rounded-lg",
                isSection ? "bg-slate-700/50" : "bg-slate-700/30"
              )}
            >
              <Icon
                className={clsx(
                  "h-5 w-5",
                  isSection ? "text-blue-400" : "text-slate-400"
                )}
              />
            </div>
          )}
          <span
            className={clsx(
              "font-semibold",
              isSection ? "text-lg" : "text-base text-slate-200"
            )}
          >
            {title}
          </span>
          {badge}
        </div>
        <motion.div
          animate={{ rotate: isOpen ? 0 : -90 }}
          transition={{ duration: 0.2 }}
        >
          <ChevronDown className="h-5 w-5 text-slate-500" />
        </motion.div>
      </button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            id={contentId}
            role="region"
            aria-labelledby={headerId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            style={{ overflow: "hidden" }}
          >
            <div
              className={clsx(
                isSection ? "px-6 pb-6" : "px-4 pb-4"
              )}
            >
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
