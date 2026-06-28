"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  SYSTEM_THEME,
  THEME_STORAGE_KEY,
  applyThemeModeToRoot,
  getThemeModeFromRoot,
  isThemeChoice,
  type ThemeChoice,
  type ThemeMode,
} from "./theme-config";

interface ThemeContextValue {
  theme: ThemeChoice;
  resolvedTheme: ThemeMode;
  setTheme: (theme: ThemeChoice) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  resolvedTheme: "dark",
  setTheme: () => {},
});

function getSystemTheme(): ThemeMode {
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function resolveTheme(theme: ThemeChoice): ThemeMode {
  return theme === SYSTEM_THEME ? getSystemTheme() : theme;
}

function getStoredTheme(): ThemeChoice {
  if (typeof window === "undefined") return SYSTEM_THEME;
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(saved) ? saved : SYSTEM_THEME;
  } catch {
    return SYSTEM_THEME;
  }
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(getStoredTheme);
  const [resolvedTheme, setResolvedTheme] = useState<ThemeMode>(() => {
    if (typeof document !== "undefined") {
      return getThemeModeFromRoot(document.documentElement);
    }
    return "dark";
  });

  // Sync theme on mount (handles SSR -> client handoff)
  useEffect(() => {
    const initial = getStoredTheme();
    setThemeState(initial);
    setResolvedTheme(resolveTheme(initial));
  }, []);

  // Listen for system theme changes when theme is "system"
  useEffect(() => {
    if (theme !== SYSTEM_THEME) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => setResolvedTheme(getSystemTheme());
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  // Apply legacy classes and the semantic theme class during the transition.
  useEffect(() => {
    applyThemeModeToRoot(document.documentElement, resolvedTheme);
  }, [resolvedTheme]);

  const setTheme = useCallback((newTheme: ThemeChoice) => {
    setThemeState(newTheme);
    setResolvedTheme(resolveTheme(newTheme));
    try {
      localStorage.setItem(THEME_STORAGE_KEY, newTheme);
    } catch {
      // localStorage unavailable (e.g. incognito/private browsing)
    }
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, resolvedTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
