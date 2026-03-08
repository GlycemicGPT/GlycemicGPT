"use client";

/**
 * GlycemicGPT Home Page.
 *
 * Story 1.3: First-Run Safety Disclaimer
 * Story 15.6: Landing Page & Auth Navigation Polish
 *
 * Shows the disclaimer modal on first visit.
 * Detects auth state to show "Go to Dashboard" for authenticated users,
 * or "Sign In" / "Create Account" buttons for visitors.
 */

import { useState, useEffect } from "react";
import Image from "next/image";
import Link from "next/link";
import { DisclaimerModal } from "@/components/disclaimer-modal";
import { AnimatedCard } from "@/components/ui/animated-card";
import { getCurrentUser } from "@/lib/api";

export default function Home() {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function checkAuth() {
      try {
        await getCurrentUser();
        if (!cancelled) setIsAuthenticated(true);
      } catch {
        if (!cancelled) setIsAuthenticated(false);
      }
    }

    checkAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <DisclaimerModal />
      <main className="flex min-h-screen flex-col items-center justify-center p-8">
        <AnimatedCard>
          <div className="text-center">
            <div className="flex justify-center mb-6">
              <Image
                src="/logo.png"
                alt="GlycemicGPT Logo"
                width={120}
                height={120}
                className="rounded-2xl"
                priority
              />
            </div>
            <h1 className="text-4xl font-bold mb-4 text-slate-900 dark:text-white">GlycemicGPT</h1>
            <p className="text-xl text-slate-500 dark:text-slate-400 mb-8">
              Your on-call endo at home
            </p>
            <div className="bg-white dark:bg-slate-800 rounded-lg p-6 max-w-md border border-slate-200 dark:border-transparent shadow-sm dark:shadow-none">
              <p className="text-slate-600 dark:text-gray-300 mb-4">
                AI-powered diabetes management platform connecting your CGM and
                pump data with actionable insights.
              </p>
              <div className="flex gap-4 justify-center">
                {isAuthenticated ? (
                  <Link
                    href="/dashboard"
                    className="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors font-medium"
                  >
                    Go to Dashboard
                  </Link>
                ) : (
                  <>
                    <Link
                      href="/login"
                      className="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors font-medium"
                    >
                      Sign In
                    </Link>
                    <Link
                      href="/register"
                      className="px-6 py-2 border border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors font-medium"
                    >
                      Create Account
                    </Link>
                  </>
                )}
              </div>
            </div>
          </div>
        </AnimatedCard>
      </main>
    </>
  );
}
