"use client";

/**
 * Dashboard Layout Component
 *
 * Story 4.1: Dashboard Layout & Navigation
 * Main layout wrapper for all dashboard pages.
 * Includes sidebar (desktop), header, and main content area.
 */

import { Sidebar } from "./sidebar";
import { Header } from "./header";

interface DashboardLayoutProps {
  children: React.ReactNode;
}

export function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div data-dashboard-root className="h-screen flex overflow-hidden bg-slate-50 dark:bg-slate-950">
      {/* Desktop sidebar -- natural flex child, no position:fixed */}
      <Sidebar />

      {/* Main content column */}
      <div data-dashboard-content className="flex-1 flex flex-col overflow-hidden">
        {/* Header -- stays at top naturally */}
        <Header />

        {/* Scrollable content area -- only scrollbar on the page */}
        <main id="main-content" className="flex-1 overflow-y-auto p-4 lg:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
