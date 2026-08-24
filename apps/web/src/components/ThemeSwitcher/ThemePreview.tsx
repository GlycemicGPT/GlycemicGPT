import { LumoseLogoIcon } from "@/components/LumoseLogoIcon";
import { twMerge } from "@/lib/ui/twMerge";
import {
  SYSTEM_THEME,
  themeModes,
  type ThemeChoice,
  type ThemeMode,
} from "@/providers/theme-config";

function PreviewLine({ className }: { className?: string }) {
  return (
    <span
      className={twMerge(
        "block h-1 rounded-pill bg-foreground-muted sm:h-2",
        className,
      )}
    />
  );
}

function PreviewCanvas({
  className,
  mode,
}: {
  className?: string;
  mode: ThemeMode;
}) {
  return (
    <span
      className={twMerge(
        themeModes[mode].semanticClass,
        "absolute inset-0 flex bg-surface-page p-1.5 sm:p-3",
        className,
      )}
      data-theme-preview-panel={mode}
    >
      <span className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-panel border border-border-default bg-surface-elevated">
        <span className="flex h-7 shrink-0 items-center gap-1.5 border-b border-border-default bg-surface-secondary px-2 sm:h-12 sm:gap-3 sm:px-4">
          <LumoseLogoIcon
            className="h-4 w-4 text-accent sm:h-7 sm:w-7"
            decorative
          />
          <PreviewLine className="w-1/3 bg-foreground-secondary" />
        </span>
        <span className="flex flex-1 flex-col justify-center gap-1 px-2 sm:gap-3 sm:px-4">
          <PreviewLine className="w-3/5 bg-foreground-secondary" />
          <PreviewLine className="w-4/5" />
          <PreviewLine className="w-2/5" />
        </span>
      </span>
    </span>
  );
}

export function ThemePreview({ theme }: { theme: ThemeChoice }) {
  return (
    <span
      aria-hidden="true"
      className="relative block aspect-square w-full overflow-hidden rounded-panel sm:aspect-[13/6]"
      data-theme-preview={theme}
    >
      {theme === SYSTEM_THEME ? (
        <>
          <PreviewCanvas mode="light" />
          <PreviewCanvas className="[clip-path:inset(0_0_0_50%)]" mode="dark" />
          <span className="absolute inset-y-0 left-1/2 w-px bg-border-default" />
        </>
      ) : (
        <PreviewCanvas mode={theme} />
      )}
    </span>
  );
}
