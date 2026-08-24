"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Icon } from "@/base";
import { LumoseLogoTextIcon } from "@/components/LumoseLogoTextIcon";
import { ActionLink } from "@/components/ActionLink";
import { PublicDisclaimerModal } from "@/components/PublicDisclaimerModal";
import { getCurrentUser } from "@/lib/api";

type AuthenticationState = "checking" | "guest" | "authenticated";

export function PublicHome() {
  const [authenticationState, setAuthenticationState] =
    useState<AuthenticationState>("checking");

  useEffect(() => {
    let cancelled = false;

    async function checkAuthentication() {
      try {
        await getCurrentUser();
        if (!cancelled) setAuthenticationState("authenticated");
      } catch {
        if (!cancelled) setAuthenticationState("guest");
      }
    }

    void checkAuthentication();

    return () => {
      cancelled = true;
    };
  }, []);

  const isAuthenticated = authenticationState === "authenticated";

  return (
    <>
      <PublicDisclaimerModal />
      <main className="min-h-screen overflow-hidden bg-surface-page text-foreground-primary">
        <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-5 py-5 sm:px-8 lg:px-12">
          <header className="border-b border-border-default pb-5">
            <Link
              aria-label="Lumose home"
              className="rounded-button text-foreground-primary outline-none focus-visible:ring-2 focus-visible:ring-border-active"
              href="/"
            >
              <LumoseLogoTextIcon className="h-8 w-52" decorative />
            </Link>
          </header>

          <section className="flex flex-1 items-center py-12 lg:py-16">
            <div className="max-w-3xl">
              <p className="font_metric_label text-accent">
                OPEN SOURCE DIABETES INTELLIGENCE
              </p>
              <h1 className="font_poppins font_header_1 mt-4 max-w-xl text-foreground-primary">
                Your diabetes data, in clearer context.
              </h1>
              <p className="font_poppins font_body_1 mt-5 max-w-xl text-foreground-secondary">
                Bring glucose, insulin, pump, and meal data together. Lumose
                helps you review patterns and prepare better questions for your
                healthcare team.
              </p>

              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                {isAuthenticated ? (
                  <ActionLink className="sm:min-w-44" href="/dashboard">
                    Go to dashboard
                    <Icon className="h-5 w-5" decorative icon="sign-in" />
                  </ActionLink>
                ) : (
                  <>
                    <ActionLink className="sm:min-w-36" href="/login">
                      Sign in
                    </ActionLink>
                    <ActionLink
                      className="sm:min-w-36"
                      href="/register"
                      variant="secondary"
                    >
                      Create account
                    </ActionLink>
                  </>
                )}
              </div>

              <p
                aria-live="polite"
                className="font_poppins font_body_3 mt-4 text-foreground-secondary"
              >
                {authenticationState === "checking"
                  ? "Checking your account status..."
                  : "Experimental software. Not medical advice."}
              </p>
            </div>
          </section>

          <footer className="font_poppins font_body_3 flex flex-col gap-2 border-t border-border-default pt-5 text-foreground-secondary sm:flex-row sm:items-center sm:justify-between">
            <p>Bring your own AI provider. Keep control of where data goes.</p>
            <p>Experimental open source software</p>
          </footer>
        </div>
      </main>
    </>
  );
}
