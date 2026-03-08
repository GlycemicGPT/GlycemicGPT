"use client";

/**
 * Header Component
 *
 * Story 4.1: Dashboard Layout & Navigation
 * Displays logo (mobile), user menu, and mobile navigation toggle.
 */

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { clsx } from "clsx";
import { User, LogOut, Settings, ChevronDown, Activity, Loader2 } from "lucide-react";
import { MobileNav } from "./sidebar";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { useUserContext } from "@/providers/user-provider";
import { logoutUser } from "@/lib/api";

interface HeaderProps {
  className?: string;
}

export function Header({ className }: HeaderProps) {
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const { user } = useUserContext();

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsUserMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <header
      className={clsx(
        "sticky top-0 z-40 flex items-center justify-between h-16 px-4 lg:px-6",
        "bg-white/95 dark:bg-slate-900/95 backdrop-blur border-b border-slate-200 dark:border-slate-800",
        className
      )}
    >
      {/* Left side - Mobile nav toggle and logo */}
      <div className="flex items-center gap-4">
        <MobileNav />

        {/* Mobile logo */}
        <Link href="/dashboard" className="flex items-center gap-2 lg:hidden">
          <Activity className="h-6 w-6 text-blue-500" />
          <span className="text-lg font-bold">GlycemicGPT</span>
        </Link>
      </div>

      {/* Right side - Theme toggle + User menu */}
      <div className="flex items-center gap-3">
        <ThemeToggle />
      <div className="relative" ref={menuRef}>
        <button
          type="button"
          onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
          className={clsx(
            "flex items-center gap-2 px-3 py-2 rounded-lg transition-colors",
            "text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800",
            isUserMenuOpen && "bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-white"
          )}
          aria-expanded={isUserMenuOpen}
          aria-haspopup="true"
        >
          <div className="flex items-center justify-center h-8 w-8 rounded-full bg-blue-600">
            <User className="h-4 w-4 text-white" />
          </div>
          <span className="hidden sm:block text-sm font-medium max-w-[120px] truncate text-slate-700 dark:text-slate-300">
            {user?.display_name || user?.email || "Account"}
          </span>
          <ChevronDown
            className={clsx(
              "h-4 w-4 transition-transform",
              isUserMenuOpen && "rotate-180"
            )}
          />
        </button>

        {/* Dropdown menu */}
        {(isUserMenuOpen || isLoggingOut) && (
          <div className="absolute right-0 mt-2 w-48 bg-white dark:bg-slate-800 rounded-lg shadow-lg border border-slate-200 dark:border-slate-700 py-1">
            <Link
              href="/dashboard/settings"
              onClick={() => setIsUserMenuOpen(false)}
              className="flex items-center gap-2 px-4 py-2 text-sm text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              <Settings className="h-4 w-4" />
              Settings
            </Link>
            <hr className="my-1 border-slate-200 dark:border-slate-700" />
            <button
              type="button"
              disabled={isLoggingOut}
              onClick={async () => {
                setIsLoggingOut(true);
                try {
                  await logoutUser();
                } catch {
                  // Best-effort logout: redirect regardless of API failure
                } finally {
                  window.location.href = "/login";
                }
              }}
              className={clsx(
                "flex items-center gap-2 w-full px-4 py-2 text-sm text-red-500 dark:text-red-400 hover:text-red-600 dark:hover:text-red-300 hover:bg-slate-100 dark:hover:bg-slate-700",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isLoggingOut ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <LogOut className="h-4 w-4" />
              )}
              {isLoggingOut ? "Signing out..." : "Sign out"}
            </button>
          </div>
        )}
      </div>
      </div>
    </header>
  );
}
