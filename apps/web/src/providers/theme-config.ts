export const THEME_STORAGE_KEY = "glycemicgpt-theme";
export const SYSTEM_THEME = "system";

export const themeModes = {
  light: {
    label: "Light",
    ariaLabel: "Light theme",
    icon: "sun",
    semanticClass: "theme-light",
    legacyClass: "light",
    colorScheme: "light",
  },
  dark: {
    label: "Dark",
    ariaLabel: "Dark theme",
    icon: "moon",
    semanticClass: "theme-dark",
    legacyClass: "dark",
    colorScheme: "dark",
  },
} as const;

export const systemThemeOption = {
  value: SYSTEM_THEME,
  label: "System",
  ariaLabel: "System theme",
  icon: "desktop-device",
} as const;

export type ThemeMode = keyof typeof themeModes;
export type ThemeChoice = ThemeMode | typeof SYSTEM_THEME;
export type LegacyTheme = (typeof themeModes)[ThemeMode]["legacyClass"];

export const themeModeNames = Object.keys(themeModes) as ThemeMode[];

export const themeOptions = [
  ...themeModeNames.map((value) => ({
    value,
    label: themeModes[value].label,
    ariaLabel: themeModes[value].ariaLabel,
    icon: themeModes[value].icon,
  })),
  systemThemeOption,
] as const;

export const rootThemeClasses = [
  "light",
  "dark",
  ...themeModeNames.map((mode) => themeModes[mode].semanticClass),
];

export function isThemeMode(value: string | null): value is ThemeMode {
  return value !== null && Object.hasOwn(themeModes, value);
}

export function isThemeChoice(value: string | null): value is ThemeChoice {
  return isThemeMode(value) || value === SYSTEM_THEME;
}

export function getThemeModeFromRoot(root: HTMLElement): ThemeMode {
  const matchingMode = themeModeNames.find((mode) =>
    root.classList.contains(themeModes[mode].semanticClass),
  );

  if (matchingMode) {
    return matchingMode;
  }

  return root.classList.contains(themeModes.dark.legacyClass) ? "dark" : "light";
}

export function applyThemeModeToRoot(root: HTMLElement, mode: ThemeMode) {
  const config = themeModes[mode];

  root.classList.remove(...rootThemeClasses);
  root.classList.add(config.legacyClass, config.semanticClass);
  root.style.colorScheme = config.colorScheme;
}

export function getThemeInitScript() {
  const modes = JSON.stringify(themeModes);
  const classes = JSON.stringify(rootThemeClasses);

  return `(function(){var k=${JSON.stringify(THEME_STORAGE_KEY)};var s=${JSON.stringify(SYSTEM_THEME)};var m=${modes};var c=${classes};function y(){return window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}function v(t){return t===s||Object.prototype.hasOwnProperty.call(m,t)}function a(r,t){var o=m[t];r.classList.remove.apply(r.classList,c);r.classList.add(o.legacyClass,o.semanticClass);r.style.colorScheme=o.colorScheme}try{var t=localStorage.getItem(k);var r=document.documentElement;if(!v(t)){t=s}a(r,t===s?y():t)}catch(e){a(document.documentElement,y())}})()`;
}
