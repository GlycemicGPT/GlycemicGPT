"use client";

import { useEffect, useRef } from "react";

interface PageTransitionProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Lightweight page fade-in using CSS transitions.
 * No framer-motion -- avoids inline transform/opacity styles that cause scroll jank.
 */
export function PageTransition({ children, className }: PageTransitionProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const prefersReduced = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) {
      el.style.opacity = "1";
      return;
    }
    // Trigger fade on next frame so the transition actually animates
    requestAnimationFrame(() => {
      el.style.opacity = "1";
    });
  }, []);

  return (
    <div
      ref={ref}
      className={className}
      style={{ opacity: 0, transition: "opacity 0.2s ease-out" }}
    >
      {children}
    </div>
  );
}
