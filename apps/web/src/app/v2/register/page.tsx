"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button, Icon } from "@/base";
import { HighlightButton } from "@/components/HighlightButton";
import { LumoseLoadingLogo } from "@/components/LumoseLoadingLogo";
import { TextInput } from "@/components/TextInput";
import { AnimatedCard } from "@/components/AnimatedCard";
import { LumoseLogoTextIcon } from "@/components/LumoseLogoTextIcon";

import { registerUser, loginUser, getCurrentUser } from "@/lib/api";
import {
  getRegisterValidationErrors,
  registerSchema,
  type RegisterField,
  type RegisterFormValues,
  type RegisterValidationErrors,
} from "../authFormSchemas";

const EMPTY_REGISTER_ERRORS: RegisterValidationErrors = {
  confirmPassword: [],
  email: [],
  password: [],
};

function isDuplicateEmailError(message: string): boolean {
  return /email.*already exists/i.test(message);
}

function LoadingScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-page">
      <div className="text-center">
        <LumoseLoadingLogo
          className="mx-auto mb-3"
          label="Loading registration"
        />
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

function RegisterForm() {
  const router = useRouter();

  // Auth check state
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);

  // Form state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [emailServerError, setEmailServerError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] =
    useState<RegisterValidationErrors>(EMPTY_REGISTER_ERRORS);

  // Check if user is already authenticated
  useEffect(() => {
    let cancelled = false;

    async function checkAuth() {
      try {
        await getCurrentUser();
        if (!cancelled) {
          router.replace("/dashboard");
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
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setEmailServerError(null);
    const validationResult = registerSchema.safeParse({
      confirmPassword,
      email,
      password,
    });

    if (!validationResult.success) {
      setValidationErrors(
        getRegisterValidationErrors({ confirmPassword, email, password }),
      );
      return;
    }

    setValidationErrors(EMPTY_REGISTER_ERRORS);
    setIsSubmitting(true);

    try {
      await registerUser(
        validationResult.data.email,
        validationResult.data.password,
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "An unexpected error occurred";

      if (isDuplicateEmailError(message)) {
        setEmailServerError(message);
      } else {
        setError(message);
      }
      setIsSubmitting(false);
      return;
    }

    try {
      await loginUser(
        validationResult.data.email,
        validationResult.data.password,
      );
      router.replace("/dashboard");
    } catch {
      // Account was created but auto-login failed; redirect to login
      router.replace("/login");
    }
  };

  const handleFieldChange = (field: RegisterField, value: string) => {
    const nextValues: RegisterFormValues = {
      confirmPassword: field === "confirmPassword" ? value : confirmPassword,
      email: field === "email" ? value : email,
      password: field === "password" ? value : password,
    };
    const currentValidationErrors = getRegisterValidationErrors(nextValues);

    if (field === "confirmPassword") {
      setConfirmPassword(value);
    } else if (field === "email") {
      setEmail(value);
      setEmailServerError(null);
    } else {
      setPassword(value);
    }

    setError(null);
    setValidationErrors((visibleErrors) => ({
      confirmPassword: visibleErrors.confirmPassword.filter((visibleError) =>
        currentValidationErrors.confirmPassword.includes(visibleError),
      ),
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
            Register
          </h1>
          <span
            aria-hidden="true"
            className="font_metric_label absolute right-2 top-2 text-foreground-primary/[0.65]"
          >
            02
          </span>
          <div className="flex justify-center py-12">
            <LumoseLogoTextIcon className="h-auto w-full text-foreground-primary" />
          </div>

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

          {/* Registration form */}
          <form className="space-y-4" noValidate onSubmit={handleSubmit}>
            <TextInput
              autoComplete="email"
              disabled={isSubmitting}
              errorMessages={[
                ...validationErrors.email,
                ...(emailServerError ? [emailServerError] : []),
              ]}
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
              autoComplete="new-password"
              disabled={isSubmitting}
              errorMessages={validationErrors.password}
              id="password"
              inputClassName="font_poppins"
              label="Password"
              onChange={(event) =>
                handleFieldChange("password", event.target.value)
              }
              placeholder="Create a password"
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

            <TextInput
              autoComplete="new-password"
              disabled={isSubmitting}
              errorMessages={validationErrors.confirmPassword}
              id="confirm-password"
              inputClassName="font_poppins"
              label="Confirm Password"
              onChange={(event) =>
                handleFieldChange("confirmPassword", event.target.value)
              }
              placeholder="Confirm your password"
              required
              trailingAdornment={
                <Button
                  aria-label={
                    showConfirmPassword
                      ? "Hide confirm password"
                      : "Show confirm password"
                  }
                  aria-pressed={showConfirmPassword}
                  className="-mr-2 flex h-8 w-8 cursor-pointer items-center justify-center rounded-button text-foreground-primary transition-colors hover:text-foreground-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-active"
                  disabled={isSubmitting}
                  onClick={() =>
                    setShowConfirmPassword((isVisible) => !isVisible)
                  }
                >
                  <Icon
                    className="h-5 w-5"
                    decorative
                    icon={showConfirmPassword ? "eye-slash" : "eye"}
                  />
                </Button>
              }
              type={showConfirmPassword ? "text" : "password"}
              value={confirmPassword}
            />

            <HighlightButton
              className="font_poppins w-full"
              disabled={isSubmitting}
              type="submit"
            >
              {isSubmitting ? (
                <>
                  <span
                    aria-hidden="true"
                    className="h-4 w-4 animate-spin rounded-pill border-2 border-current border-r-transparent"
                  />
                  Creating Account...
                </>
              ) : (
                <>
                  <Icon className="h-5 w-5" decorative icon="person-add" />
                  Create Account
                </>
              )}
            </HighlightButton>
          </form>

          {/* Navigation links */}
          <div className="mt-6 space-y-2 text-center">
            <p className="font_poppins font_body_3 text-foreground-primary/[0.65]">
              Already have an account?{" "}
              <Link
                href="/login"
                className="rounded-button text-foreground-primary underline decoration-accent underline-offset-2 transition-colors hover:decoration-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-active"
              >
                Sign in
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

export default function RegisterPage() {
  return (
    <Suspense fallback={<LoadingScreen />}>
      <RegisterForm />
    </Suspense>
  );
}
