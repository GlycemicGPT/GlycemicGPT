"use client";

import { Sun, Moon, Monitor } from "lucide-react";
import { clsx } from "clsx";
import { useTheme } from "@/providers";

const options = [
  { value: "light" as const, icon: Sun, label: "Light theme" },
  { value: "dark" as const, icon: Moon, label: "Dark theme" },
  { value: "system" as const, icon: Monitor, label: "System theme" },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div
      className="flex items-center rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 p-0.5"
      role="radiogroup"
      aria-label="Theme selection"
    >
      {options.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={theme === value}
          aria-label={label}
          onClick={() => setTheme(value)}
          className={clsx(
            "p-1.5 rounded-md transition-colors",
            theme === value
              ? "bg-blue-600 text-white"
              : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200"
          )}
        >
          <Icon className="h-3.5 w-3.5" />
        </button>
      ))}
    </div>
  );
}
