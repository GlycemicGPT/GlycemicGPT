"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button, Icon } from "@/base";
import { HighlightButton } from "@/components/HighlightButton";
import { LumoseLoadingLogo } from "@/components/LumoseLoadingLogo";
import { TextInput } from "@/components/TextInput";
import { AnimatedCard } from "@/components/AnimatedCard";
import { LumoseLogoTextIcon } from "@/components/LumoseLogoTextIcon";

import { loginUser, getCurrentUser, verifySessionCookie } from "@/lib/api";
import {
  getLoginValidationErrors,
  loginSchema,
  type LoginField,
  type LoginFormValues,
  type LoginValidationErrors,
} from "../authFormSchemas";

const EMPTY_LOGIN_ERRORS: LoginValidationErrors = {
  email: [],
  password: [],
};

function getRedirectTarget(searchParams: URLSearchParams): string {
  const redirect = searchParams.get("redirect");
  return redirect && /^\/(dashboard|settings)(?:[/?#]|$)/.test(redirect)
    ? redirect
    : "/dashboard";
}

function LoadingScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-page">
      <div className="text-center">
        <LumoseLoadingLogo className="mx-auto mb-3" label="Loading sign in" />
        <p
          aria-hidden="true"
          className="font_poppins font_body_3 text-foreground-secondary"
        >
          Loading...
        </p>
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
  const [validationErrors, setValidationErrors] =
    useState<LoginValidationErrors>(EMPTY_LOGIN_ERRORS);

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
    const validationResult = loginSchema.safeParse({ email, password });

    if (!validationResult.success) {
      setValidationErrors(getLoginValidationErrors({ email, password }));
      return;
    }

    setValidationErrors(EMPTY_LOGIN_ERRORS);
    setIsSubmitting(true);

    try {
      await loginUser(
        validationResult.data.email,
        validationResult.data.password,
      );
      // Verify the session cookie actually saved. When the deploy is
      // over plain HTTP from a non-localhost host, the browser drops the
      // Secure cookie silently and /api/auth/me returns 401 even though
      // login returned 200. We inspect the status code directly so a
      // transient 5xx or network blip doesn't get misattributed to the
      // cookie issue.
      const verifyStatus = await verifySessionCookie();
      if (verifyStatus === 401) {
        setError(
          "Login succeeded, but your browser did not store the session " +
            "cookie. This usually means Lumose is being served over " +
            "plain HTTP from a non-localhost address — browsers refuse to " +
            "store secure cookies in that case. Fix: serve Lumose " +
            "over HTTPS. As a LAN-only / local-dev workaround (not safe " +
            "for any internet-exposed deployment, since session tokens " +
            "and personal health data would travel in clear text) you " +
            "can set COOKIE_SECURE=false in your docker-compose.yml. See " +
            "https://github.com/glycemicgpt/glycemicgpt/blob/main/docs/install/docker.md#troubleshooting.",
        );
        setIsSubmitting(false);
        return;
      }
      if (verifyStatus >= 400) {
        setError(
          `Could not verify your session (status ${verifyStatus}). ` +
            "Check the API logs and try again.",
        );
        setIsSubmitting(false);
        return;
      }
      router.replace(getRedirectTarget(searchParams));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "An unexpected error occurred",
      );
      setIsSubmitting(false);
    }
  };

  const handleFieldChange = (field: LoginField, value: string) => {
    const nextValues: LoginFormValues = {
      email: field === "email" ? value : email,
      password: field === "password" ? value : password,
    };
    const currentValidationErrors = getLoginValidationErrors(nextValues);

    if (field === "email") {
      setEmail(value);
    } else {
      setPassword(value);
    }

    setError(null);
    setValidationErrors((visibleErrors) => ({
      email: visibleErrors.email.filter((visibleError) =>
        currentValidationErrors.email.includes(visibleError),
      ),
      password: visibleErrors.password.filter((visibleError) =>
        currentValidationErrors.password.includes(visibleError),
      ),
    }));
  };

  if (isCheckingAuth) {
    return <LoadingScreen />;
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-page p-4 text-foreground-primary">
      <AnimatedCard className="w-full max-w-sm">
        <div className="relative w-full rounded-panel border border-border-default bg-surface-elevated p-8 shadow-sm">
          {/* Branding */}
          <h1 className="font_metric_label absolute left-2 top-2 text-foreground-primary/[0.65]">
            Sign In
          </h1>
          <span
            aria-hidden="true"
            className="font_metric_label absolute right-2 top-2 text-foreground-primary/[0.65]"
          >
            01
          </span>
          <div className="flex justify-center py-12">
            <LumoseLogoTextIcon className="h-auto w-full text-foreground-primary" />
          </div>

          {/* Expired session banner */}
          {expired && (
            <div
              className="font_poppins font_body_3 mb-4 rounded-panel border border-signal-warning-text bg-surface-primary p-3 text-signal-warning-text"
              role="alert"
            >
              Your session has expired. Please sign in again.
            </div>
          )}

          {/* Error banner */}
          {error && (
            <div
              className="font_poppins font_body_3 mb-4 flex items-start gap-2 text-signal-error-text"
              role="alert"
            >
              <Icon
                className="mt-0.5 h-5 w-5 shrink-0"
                decorative
                icon="alert"
              />
              <p>{error}</p>
            </div>
          )}

          {/* Login form */}
          <form className="space-y-4" noValidate onSubmit={handleSubmit}>
            <TextInput
              autoComplete="email"
              disabled={isSubmitting}
              errorMessages={validationErrors.email}
              id="email"
              inputClassName="font_poppins"
              label="Email"
              onChange={(event) =>
                handleFieldChange("email", event.target.value)
              }
              placeholder="your@email.com"
              required
              type="email"
              value={email}
            />

            <TextInput
              autoComplete="current-password"
              disabled={isSubmitting}
              errorMessages={validationErrors.password}
              id="password"
              inputClassName="font_poppins"
              label="Password"
              onChange={(event) =>
                handleFieldChange("password", event.target.value)
              }
              placeholder="Enter your password"
              required
              trailingAdornment={
                <Button
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-pressed={showPassword}
                  className="-mr-2 flex h-8 w-8 cursor-pointer items-center justify-center rounded-button text-foreground-primary transition-colors hover:text-foreground-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-active"
                  disabled={isSubmitting}
                  onClick={() => setShowPassword((isVisible) => !isVisible)}
                >
                  <Icon
                    className="h-5 w-5"
                    decorative
                    icon={showPassword ? "eye-slash" : "eye"}
                  />
                </Button>
              }
              type={showPassword ? "text" : "password"}
              value={password}
            />

            <HighlightButton
              className="font_poppins w-full"
              type="submit"
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <span
                    aria-hidden="true"
                    className="h-4 w-4 animate-spin rounded-pill border-2 border-current border-r-transparent"
                  />
                  Signing In...
                </>
              ) : (
                <>
                  <Icon className="h-5 w-5" decorative icon="sign-in" />
                  Sign In
                </>
              )}
            </HighlightButton>
          </form>

          {/* Navigation links */}
          <div className="mt-6 space-y-2 text-center">
            <p className="font_poppins font_body_3 text-foreground-primary/[0.65]">
              Don&apos;t have an account?{" "}
              <Link
                href="/register"
                className="rounded-button text-foreground-primary underline decoration-accent underline-offset-2 transition-colors hover:decoration-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-active"
              >
                Register
              </Link>
            </p>
            <p className="font_poppins font_body_4 text-foreground-primary/[0.65]">
              <Link
                href="/"
                className="rounded-button transition-colors hover:text-foreground-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-active"
              >
                Back to home
              </Link>
            </p>
          </div>
        </div>
      </AnimatedCard>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoadingScreen />}>
      <LoginForm />
    </Suspense>
  );
}
