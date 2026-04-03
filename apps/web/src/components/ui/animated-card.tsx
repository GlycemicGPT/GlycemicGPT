"use client";

import { useEffect, useRef } from "react";

interface AnimatedCardProps {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}

/**
 * Lightweight fade-in card using CSS transitions.
 * No framer-motion -- avoids inline transform/opacity styles that cause scroll jank.
 */
export function AnimatedCard({ children, delay = 0, className }: AnimatedCardProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const prefersReduced = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) {
      el.style.transition = "none";
      el.style.opacity = "1";
      return;
    }
    const timeout = setTimeout(() => {
      el.style.opacity = "1";
    }, delay * 1000);
    return () => clearTimeout(timeout);
  }, [delay]);

  return (
    <div
      ref={ref}
      className={className}
      style={{ opacity: 0, transition: "opacity 0.3s ease-out" }}
    >
      {children}
    </div>
  );
}
