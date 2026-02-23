"use client";

/**
 * Settings Page
 *
 * Story 4.1: Dashboard Layout & Navigation
 * Story 8.3: Role-aware settings — caregivers only see Profile & Telegram.
 */

import Link from "next/link";
import { Settings, User, Bell, Database, Link2, Users, Radio, UserPlus, Target, Clock, Brain, Syringe, ShieldCheck } from "lucide-react";
import { useUserContext } from "@/providers";

interface SettingsSection {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  href: string;
  caregiverVisible?: boolean;
}

const settingsSections: SettingsSection[] = [
  {
    title: "Profile",
    description: "Manage your account and personal information",
    icon: User,
    href: "/dashboard/settings/profile",
    caregiverVisible: true,
  },
  {
    title: "Integrations",
    description: "Connect Dexcom, Tandem, and other data sources",
    icon: Link2,
    href: "/dashboard/settings/integrations",
  },
  {
    title: "AI Provider",
    description: "Configure Claude or OpenAI for glucose analysis and insights",
    icon: Brain,
    href: "/dashboard/settings/ai-provider",
  },
  {
    title: "Glucose Range",
    description: "Set your target glucose range for dashboard and AI analysis",
    icon: Target,
    href: "/dashboard/settings/glucose-range",
  },
  {
    title: "Insulin / Medications",
    description: "Configure your insulin type for IoB calculations",
    icon: Syringe,
    href: "/dashboard/settings/insulin",
  },
  {
    title: "Safety Limits",
    description: "Platform-enforced bounds for data validation and delivery rates",
    icon: ShieldCheck,
    href: "/dashboard/settings/safety-limits",
  },
  {
    title: "Daily Briefs",
    description: "Configure delivery time, timezone, and channel for daily briefs",
    icon: Clock,
    href: "/dashboard/settings/brief-delivery",
  },
  {
    title: "Alerts",
    description: "Configure alert thresholds and escalation",
    icon: Bell,
    href: "/dashboard/settings/alerts",
  },
  {
    title: "Emergency Contacts",
    description: "Manage contacts for alert escalation via Telegram",
    icon: Users,
    href: "/dashboard/settings/emergency-contacts",
  },
  {
    title: "Caregivers",
    description: "Invite caregivers to monitor your glucose data",
    icon: UserPlus,
    href: "/dashboard/settings/caregivers",
  },
  {
    title: "Communications",
    description: "Configure Telegram and other notification channels",
    icon: Radio,
    href: "/dashboard/settings/communications",
    caregiverVisible: true,
  },
  {
    title: "Data",
    description: "Manage data retention and export options",
    icon: Database,
    href: "/dashboard/settings/data",
  },
];

export default function SettingsPage() {
  const { user } = useUserContext();
  const isCaregiver = user?.role === "caregiver";
  const visibleSections = isCaregiver
    ? settingsSections.filter((s) => s.caregiverVisible)
    : settingsSections;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-slate-400">Manage your account and preferences</p>
      </div>

      {/* Settings sections grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {visibleSections.map((section) => (
          <Link
            key={section.title}
            href={section.href}
            className="bg-slate-900 rounded-xl p-6 border border-slate-800 hover:border-slate-700 transition-colors group"
          >
            <div className="flex items-start gap-4">
              <div className="p-3 bg-slate-800 rounded-lg group-hover:bg-slate-700 transition-colors">
                <section.icon className="h-6 w-6 text-slate-400 group-hover:text-white transition-colors" />
              </div>
              <div>
                <h2 className="text-lg font-semibold group-hover:text-white transition-colors">
                  {section.title}
                </h2>
                <p className="text-slate-400 text-sm mt-1">
                  {section.description}
                </p>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {/* Disclaimer */}
      <div className="bg-slate-900/50 rounded-xl p-4 border border-slate-800">
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Settings className="h-4 w-4" />
          <span>
            Additional settings will be available as features are implemented.
          </span>
        </div>
      </div>
    </div>
  );
}
