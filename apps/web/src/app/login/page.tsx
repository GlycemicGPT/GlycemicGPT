"use client";

/**
 * Story 15.1: Login Page
 *
 * Email/password login form with redirect to dashboard on success.
 * Redirects already-authenticated users to the dashboard.
 */

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import {
  LogIn,
  Loader2,
  AlertTriangle,
  Eye,
  EyeOff,
  Info,
} from "lucide-react";
import clsx from "clsx";
import { AnimatedCard } from "@/components/ui/animated-card";
import { loginUser, getCurrentUser } from "@/lib/api";

function getRedirectTarget(searchParams: URLSearchParams): string {
  const redirect = searchParams.get("redirect");
  return redirect &&
    (redirect === "/dashboard" || redirect.startsWith("/dashboard/"))
    ? redirect
    : "/dashboard";
}

function LoadingSpinner() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
        <p className="text-slate-500 dark:text-slate-400">Loading...</p>
      </div>
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Auth check state
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);

  // Form state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Expired session banner
  const expired = searchParams.get("expired") === "true";

  // Check if user is already authenticated
  useEffect(() => {
    let cancelled = false;

    async function checkAuth() {
      try {
        await getCurrentUser();
        if (!cancelled) {
          router.replace(getRedirectTarget(searchParams));
        }
      } catch {
        if (!cancelled) {
          setIsCheckingAuth(false);
        }
      }
    }

    checkAuth();
    return () => {
      cancelled = true;
    };
  }, [router, searchParams]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      await loginUser(email.trim(), password);
      router.replace(getRedirectTarget(searchParams));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "An unexpected error occurred"
      );
      setIsSubmitting(false);
    }
  };

  if (isCheckingAuth) {
    return <LoadingSpinner />;
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <AnimatedCard>
        <div className="max-w-md w-full bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-8 shadow-sm dark:shadow-none">
          {/* Branding */}
          <div className="text-center mb-6">
            <div className="flex justify-center mb-4">
              <Image
                src="/logo.png"
                alt="GlycemicGPT"
                width={64}
                height={64}
                className="rounded-xl"
                priority
              />
            </div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-200">Sign In</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              Welcome back to GlycemicGPT
            </p>
          </div>

          {/* Expired session banner */}
          {expired && (
            <div
              className="bg-amber-500/10 rounded-lg p-3 border border-amber-500/20 mb-4"
              role="alert"
            >
              <div className="flex items-center gap-2">
                <Info className="h-4 w-4 text-amber-400 shrink-0" />
                <p className="text-sm text-amber-400">
                  Your session has expired. Please sign in again.
                </p>
              </div>
            </div>
          )}

          {/* Error banner */}
          {error && (
            <div
              className="bg-red-500/10 rounded-lg p-3 border border-red-500/20 mb-4"
              role="alert"
            >
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
                <p className="text-sm text-red-400">{error}</p>
              </div>
            </div>
          )}

          {/* Login form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
              >
                Email Address
              </label>
              <input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={clsx(
                  "w-full rounded-lg border px-3 py-2 text-sm",
                  "bg-slate-50 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  "placeholder:text-slate-400 dark:placeholder:text-slate-500"
                )}
                placeholder="your@email.com"
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
              >
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  required
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className={clsx(
                    "w-full rounded-lg border px-3 py-2 pr-10 text-sm",
                    "bg-slate-50 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-200",
                    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                    "placeholder:text-slate-400 dark:placeholder:text-slate-500"
                  )}
                  placeholder="Enter your password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className={clsx(
                "w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium",
                "bg-blue-600 text-white hover:bg-blue-500",
                "transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Signing In...
                </>
              ) : (
                <>
                  <LogIn className="h-4 w-4" />
                  Sign In
                </>
              )}
            </button>
          </form>

          {/* Navigation links */}
          <div className="mt-6 text-center space-y-2">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Don&apos;t have an account?{" "}
              <Link
                href="/register"
                className="text-blue-600 dark:text-blue-400 hover:text-blue-500 dark:hover:text-blue-300"
              >
                Register
              </Link>
            </p>
            <p className="text-xs text-slate-400 dark:text-slate-500">
              <Link href="/" className="hover:text-slate-600 dark:hover:text-slate-400">
                Back to home
              </Link>
            </p>
          </div>
        </div>
      </AnimatedCard>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoadingSpinner />}>
      <LoginForm />
    </Suspense>
  );
}
