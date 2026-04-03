"use client";

/**
 * Story 8.1: Caregiver Invitation Acceptance Page
 *
 * Public page (no auth required) where caregivers create an account
 * and accept a patient's invitation to link.
 */

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  UserPlus,
  Loader2,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  Eye,
  EyeOff,
} from "lucide-react";
import clsx from "clsx";
import {
  getInvitationDetails,
  acceptCaregiverInvitation,
  type InvitationDetail,
} from "@/lib/api";

export default function InviteAcceptPage() {
  const params = useParams();
  const router = useRouter();
  const token = params.token as string;

  const [invitation, setInvitation] = useState<InvitationDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Form state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchDetails = useCallback(async () => {
    try {
      setError(null);
      const data = await getInvitationDetails(token);
      setInvitation(data);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to load invitation details"
      );
    } finally {
      setIsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchDetails();
  }, [fetchDetails]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (password !== confirmPassword) {
      setFormError("Passwords do not match");
      return;
    }

    if (password.length < 8) {
      setFormError("Password must be at least 8 characters");
      return;
    }

    if (!/[a-z]/.test(password) || !/[A-Z]/.test(password) || !/\d/.test(password)) {
      setFormError(
        "Password must include uppercase, lowercase, and a number"
      );
      return;
    }

    setIsSubmitting(true);

    try {
      await acceptCaregiverInvitation(token, email, password);
      setSuccess(true);
      // Redirect to login after 3 seconds
      setTimeout(() => {
        router.push("/login");
      }, 3000);
    } catch (err) {
      setFormError(
        err instanceof Error ? err.message : "Failed to accept invitation"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-500 dark:text-slate-400">Loading invitation...</p>
        </div>
      </div>
    );
  }

  // Error state (invalid/not found token)
  if (error || !invitation) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-8 text-center">
          <XCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
          <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200 mb-2">
            Invalid Invitation
          </h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm">
            {error || "This invitation link is invalid or has expired."}
          </p>
          <Link
            href="/"
            className="inline-block mt-6 px-4 py-2 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded-lg text-sm hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          >
            Go to Home
          </Link>
        </div>
      </div>
    );
  }

  // Expired or revoked
  if (invitation.status !== "pending") {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-8 text-center">
          {invitation.status === "accepted" ? (
            <>
              <CheckCircle className="h-12 w-12 text-green-400 mx-auto mb-4" />
              <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200 mb-2">
                Already Accepted
              </h1>
              <p className="text-slate-500 dark:text-slate-400 text-sm">
                This invitation has already been accepted. You can log in to
                your account.
              </p>
            </>
          ) : (
            <>
              <Clock className="h-12 w-12 text-slate-500 mx-auto mb-4" />
              <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200 mb-2">
                Invitation{" "}
                {invitation.status === "expired" ? "Expired" : "Revoked"}
              </h1>
              <p className="text-slate-500 dark:text-slate-400 text-sm">
                This invitation is no longer valid. Please ask{" "}
                {invitation.patient_email} to send a new invitation.
              </p>
            </>
          )}
          <Link
            href="/"
            className="inline-block mt-6 px-4 py-2 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded-lg text-sm hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          >
            Go to Home
          </Link>
        </div>
      </div>
    );
  }

  // Success state
  if (success) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-8 text-center">
          <CheckCircle className="h-12 w-12 text-green-400 mx-auto mb-4" />
          <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200 mb-2">
            Account Created!
          </h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm mb-4">
            Your caregiver account has been created and linked to{" "}
            {invitation.patient_email}. You can now monitor their glucose data
            via the Telegram bot.
          </p>
          <p className="text-xs text-slate-500">
            Redirecting to login...
          </p>
        </div>
      </div>
    );
  }

  // Pending — show registration form
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center p-4">
      <div className="max-w-md w-full bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-8">
        <div className="text-center mb-6">
          <UserPlus className="h-12 w-12 text-blue-400 mx-auto mb-4" />
          <h1 className="text-xl font-bold text-slate-800 dark:text-slate-200 mb-2">
            Caregiver Invitation
          </h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm">
            <span className="text-blue-700 dark:text-blue-400">{invitation.patient_email}</span>{" "}
            has invited you to be their caregiver on GlycemicGPT.
          </p>
          <p className="text-xs text-slate-500 mt-2">
            Expires {new Date(invitation.expires_at).toLocaleDateString()}
          </p>
        </div>

        {formError && (
          <div
            className="bg-red-500/10 rounded-lg p-3 border border-red-500/20 mb-4"
            role="alert"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
              <p className="text-sm text-red-400">{formError}</p>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4" aria-label="Caregiver account registration">
          <div>
            <label
              htmlFor="email"
              className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
            >
              Email Address
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={clsx(
                "w-full rounded-lg border px-3 py-2 text-sm",
                "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200",
                "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                "placeholder:text-slate-500"
              )}
              placeholder="your@email.com"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
            >
              Password
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                required
                minLength={8}
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={clsx(
                  "w-full rounded-lg border px-3 py-2 pr-10 text-sm",
                  "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200",
                  "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                  "placeholder:text-slate-500"
                )}
                placeholder="Min 8 chars, upper, lower, number"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
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

          <div>
            <label
              htmlFor="confirm-password"
              className="block text-sm font-medium text-slate-600 dark:text-slate-300 mb-1"
            >
              Confirm Password
            </label>
            <input
              id="confirm-password"
              type={showPassword ? "text" : "password"}
              required
              minLength={8}
              maxLength={128}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className={clsx(
                "w-full rounded-lg border px-3 py-2 text-sm",
                "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200",
                "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
                "placeholder:text-slate-500"
              )}
              placeholder="Confirm your password"
            />
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
                Creating Account...
              </>
            ) : (
              <>
                <UserPlus className="h-4 w-4" />
                Create Account & Accept
              </>
            )}
          </button>
        </form>

        <p className="text-xs text-slate-500 text-center mt-4">
          Already have a caregiver account?{" "}
          <Link href="/login" className="text-blue-400 hover:text-blue-300">
            Log in
          </Link>{" "}
          first, then visit this link again.
        </p>
      </div>
    </div>
  );
}
