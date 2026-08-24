"use client";

import Image from "next/image";
import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { Button, Icon } from "@/base";
import { Accordion } from "@/components/Accordion";
import { Checkbox } from "@/components/Checkbox";
import { icons, type IconName } from "@/base/Icon/iconConfig";
import { HighlightButton } from "@/components/HighlightButton";
import { LumoseLoadingLogo } from "@/components/LumoseLoadingLogo";
import { LumoseLogoIcon } from "@/components/LumoseLogoIcon";
import { LumoseLogoTextIcon } from "@/components/LumoseLogoTextIcon";
import { PrimaryButton } from "@/components/PrimaryButton";
import { SecondaryButton } from "@/components/SecondaryButton";
import { TelegramLogo } from "@/components/TelegramLogo";
import { TextInput } from "@/components/TextInput";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { twMerge } from "@/lib/ui/twMerge";

type DesignSystemSection =
  "colors" | "components" | "icons" | "assets" | "fonts";

type ColorToken = {
  name: string;
  variable: string;
  light: string;
  dark: string;
  note: string;
};

type ColorGroup = {
  name: string;
  description: string;
  tokens: ColorToken[];
};

type FontRole = {
  name: string;
  className: string;
  sample: string;
};

type FontFamily = {
  label: string;
  name: string;
  className: string;
};

type FontGroup = {
  title: string;
  roles: FontRole[];
};

type ComponentExample = {
  name: string;
  description: string;
  example?: React.ReactNode;
  preview: React.ReactNode;
};

type ImageAsset = {
  height: number;
  label: string;
  path: string;
  previewAtNativeSize?: boolean;
  previewClassName: string;
  width: number;
};

const sectionTabs: Array<{
  id: DesignSystemSection;
  label: string;
}> = [
  { id: "colors", label: "Colors" },
  { id: "components", label: "Components" },
  { id: "icons", label: "Icons" },
  { id: "assets", label: "Assets" },
  { id: "fonts", label: "Fonts" },
];

const imageAssets = [
  {
    height: 16,
    label: "Favicon 16 px",
    path: "/favicon-16x16.png",
    previewAtNativeSize: true,
    previewClassName: "bg-surface-secondary",
    width: 16,
  },
  {
    height: 32,
    label: "Favicon 32 px",
    path: "/favicon-32x32.png",
    previewAtNativeSize: true,
    previewClassName: "bg-surface-secondary",
    width: 32,
  },
  {
    height: 180,
    label: "Apple touch icon",
    path: "/apple-touch-icon.png",
    previewClassName: "bg-surface-secondary",
    width: 180,
  },
  {
    height: 192,
    label: "App icon 192 px",
    path: "/icon-192.png",
    previewClassName: "bg-surface-secondary",
    width: 192,
  },
  {
    height: 512,
    label: "App icon 512 px",
    path: "/icon-512.png",
    previewClassName: "bg-surface-secondary",
    width: 512,
  },
  {
    height: 512,
    label: "Maskable app icon",
    path: "/icon-maskable-512.png",
    previewClassName: "bg-surface-secondary",
    width: 512,
  },
  {
    height: 1920,
    label: "Lumose icon on dark",
    path: "/static_assets/logos/lumose-logo-icon-on-dark.jpg",
    previewClassName: "bg-surface-inverse",
    width: 1920,
  },
  {
    height: 301,
    label: "Lumose icon then wordmark, black",
    path: "/static_assets/logos/lumose-logo-icon-text-black.png",
    previewClassName: "bg-surface-primary",
    width: 1920,
  },
  {
    height: 535,
    label: "Lumose icon then wordmark, on dark",
    path: "/static_assets/logos/lumose-logo-icon-text-on-dark.jpg",
    previewClassName: "bg-surface-inverse",
    width: 1920,
  },
  {
    height: 535,
    label: "Lumose icon then wordmark, on light",
    path: "/static_assets/logos/lumose-logo-icon-text-on-light.jpg",
    previewClassName: "bg-surface-primary",
    width: 1920,
  },
  {
    height: 301,
    label: "Lumose icon then wordmark, white",
    path: "/static_assets/logos/lumose-logo-icon-text-white.png",
    previewClassName: "bg-surface-inverse",
    width: 1920,
  },
  {
    height: 301,
    label: "Lumose wordmark with icon, black",
    path: "/static_assets/logos/lumose-logo-text-icon-black.png",
    previewClassName: "bg-surface-primary",
    width: 1920,
  },
  {
    height: 579,
    label: "Lumose wordmark with icon, on dark",
    path: "/static_assets/logos/lumose-logo-text-icon-on-dark.jpg",
    previewClassName: "bg-surface-inverse",
    width: 1920,
  },
  {
    height: 579,
    label: "Lumose wordmark with icon, on light",
    path: "/static_assets/logos/lumose-logo-text-icon-on-light.jpg",
    previewClassName: "bg-surface-primary",
    width: 1920,
  },
] as const satisfies ReadonlyArray<ImageAsset>;

const designSystemFontStyle = {
  "--font-sans": "var(--font-poppins), ui-sans-serif, system-ui, sans-serif",
  "--font-label":
    'var(--font-jetbrains-mono), ui-monospace, "SFMono-Regular", Consolas, monospace',
} as CSSProperties;

const semanticColorGroups: ColorGroup[] = [
  {
    name: "Surface",
    description: "Layout backgrounds, panels, and inverse regions.",
    tokens: [
      {
        name: "Primary",
        variable: "--color-surface-primary",
        light: "--color-base-white",
        dark: "--color-base-eerie-black",
        note: "Primary surfaces",
      },
      {
        name: "Secondary",
        variable: "--color-surface-secondary",
        light: "--color-base-mist",
        dark: "--color-base-dim-gray",
        note: "Secondary panels",
      },
      {
        name: "Tertiary",
        variable: "--color-surface-tertiary",
        light: "--color-base-silver",
        dark: "--color-base-cadet-gray",
        note: "Raised accents",
      },
      {
        name: "Inverse",
        variable: "--color-surface-inverse",
        light: "--color-base-ink",
        dark: "--color-base-cool-silver",
        note: "Inverse surfaces",
      },
    ],
  },
  {
    name: "Foreground",
    description: "Text and icon colors for each content emphasis.",
    tokens: [
      {
        name: "Primary",
        variable: "--color-foreground-primary",
        light: "--color-base-ink",
        dark: "--color-base-cool-silver",
        note: "Primary text",
      },
      {
        name: "Secondary",
        variable: "--color-foreground-secondary",
        light: "--color-base-grey",
        dark: "--color-base-cadet-gray-light",
        note: "Secondary text",
      },
      {
        name: "Muted",
        variable: "--color-foreground-muted",
        light: "--color-base-silver",
        dark: "--color-base-dim-gray",
        note: "Quiet text",
      },
      {
        name: "Inverse",
        variable: "--color-foreground-inverse",
        light: "--color-base-white",
        dark: "--color-base-eerie-black",
        note: "Text on inverse surfaces",
      },
    ],
  },
  {
    name: "Accent",
    description: "Action colors and text placed on action backgrounds.",
    tokens: [
      {
        name: "Accent",
        variable: "--color-accent",
        light: "--color-base-accent-blue",
        dark: "--color-base-accent-blue",
        note: "Primary action",
      },
      {
        name: "Hover",
        variable: "--color-accent-hover",
        light: "--color-base-accent-blue-hover-light",
        dark: "--color-base-accent-blue-hover-dark",
        note: "Action hover",
      },
      {
        name: "Active",
        variable: "--color-accent-active",
        light: "--color-base-ink",
        dark: "--color-base-cool-silver",
        note: "Action active",
      },
      {
        name: "Foreground",
        variable: "--color-accent-foreground",
        light: "--color-base-ink",
        dark: "--color-base-ink",
        note: "Text on accent",
      },
    ],
  },
  {
    name: "Border",
    description: "Default, hover, active, disabled, and invisible borders.",
    tokens: [
      {
        name: "Default",
        variable: "--color-border-default",
        light: "--color-base-mist",
        dark: "--color-base-dim-gray",
        note: "Default borders",
      },
      {
        name: "Hover",
        variable: "--color-border-hover",
        light: "--color-base-silver",
        dark: "--color-base-cadet-gray",
        note: "Hover borders",
      },
      {
        name: "Active",
        variable: "--color-border-active",
        light: "--color-base-ink",
        dark: "--color-base-cool-silver",
        note: "Focus and active borders",
      },
      {
        name: "Disabled",
        variable: "--color-border-disabled",
        light: "--color-base-mist",
        dark: "--color-base-dim-gray",
        note: "Disabled borders",
      },
      {
        name: "Null",
        variable: "--color-border-null",
        light: "transparent",
        dark: "transparent",
        note: "No visible border",
      },
    ],
  },
  {
    name: "Signal fills",
    description:
      "Background colors for indicators, diagrams, charts, and status-like states.",
    tokens: [
      {
        name: "Partial",
        variable: "--color-signal-partial-fill",
        light: "--color-base-purple-600",
        dark: "--color-base-purple-300",
        note: "Partial fill",
      },
      {
        name: "Info",
        variable: "--color-signal-info-fill",
        light: "--color-base-teal-700",
        dark: "--color-base-teal-400",
        note: "Info fill",
      },
      {
        name: "Check",
        variable: "--color-signal-check-fill",
        light: "--color-base-mint-700",
        dark: "--color-base-mint-400",
        note: "Check fill",
      },
      {
        name: "Warning",
        variable: "--color-signal-warning-fill",
        light: "--color-base-yellow-400",
        dark: "--color-base-yellow-500",
        note: "Warning fill",
      },
      {
        name: "Error",
        variable: "--color-signal-error-fill",
        light: "--color-base-red-600",
        dark: "--color-base-red-500",
        note: "Error fill",
      },
    ],
  },
  {
    name: "Signal text",
    description: "Signal-colored text and icons on approved neutral surfaces.",
    tokens: [
      {
        name: "Partial",
        variable: "--color-signal-partial-text",
        light: "--color-base-purple-600",
        dark: "--color-base-purple-100",
        note: "Partial text",
      },
      {
        name: "Info",
        variable: "--color-signal-info-text",
        light: "--color-base-teal-700",
        dark: "--color-base-teal-200",
        note: "Info text",
      },
      {
        name: "Check",
        variable: "--color-signal-check-text",
        light: "--color-base-mint-700",
        dark: "--color-base-mint-200",
        note: "Check text",
      },
      {
        name: "Warning",
        variable: "--color-signal-warning-text",
        light: "--color-base-yellow-700",
        dark: "--color-base-yellow-200",
        note: "Warning text",
      },
      {
        name: "Error",
        variable: "--color-signal-error-text",
        light: "--color-base-red-600",
        dark: "--color-base-red-100",
        note: "Error text",
      },
    ],
  },
  {
    name: "Overlay",
    description: "Scrim colors used above app surfaces.",
    tokens: [
      {
        name: "Primary",
        variable: "--color-overlay-primary",
        light: "--color-base-opacity-dark-50",
        dark: "--color-base-opacity-light-30",
        note: "Modal and drawer scrims",
      },
    ],
  },
];

const fontFamilies: FontFamily[] = [
  {
    label: "Primary",
    name: "Poppins",
    className: "font_poppins",
  },
  {
    label: "Labels",
    name: "JetBrains Mono",
    className: "font_jetbrains_mono",
  },
];

const bodyFontSample =
  "Lorem ipsum dolor sit amet, temporibus mattis cotidieque tempor vituperatoribus affert reprehendunt tellus veri consul posuere ante iaculis phasellus vivamus ornare mnesarchum auctor partem simul felis faucibus ullamcorper aenean vocibus deterruisset postulant nonumes mauris iudicabit maiorum pri ut nibh ultricies.";

const fontGroups: FontGroup[] = [
  {
    title: "Headings",
    roles: [
      {
        name: "header 1",
        className: "font_header_1",
        sample: "Lorem ipsum dolor",
      },
      {
        name: "header 2",
        className: "font_header_2",
        sample: "Lorem ipsum dolor",
      },
      {
        name: "header 3",
        className: "font_header_3",
        sample: "Lorem ipsum dolor",
      },
      {
        name: "header 4",
        className: "font_header_4",
        sample: "Lorem ipsum dolor",
      },
    ],
  },
  {
    title: "Body",
    roles: [
      {
        name: "body 1",
        className: "font_body_1",
        sample: bodyFontSample,
      },
      { name: "body 2", className: "font_body_2", sample: bodyFontSample },
      { name: "body 3", className: "font_body_3", sample: bodyFontSample },
      { name: "body 4", className: "font_body_4", sample: bodyFontSample },
    ],
  },
  {
    title: "Labels",
    roles: [
      {
        name: "metric label",
        className: "font_metric_label",
        sample: "Lorem ipsum dolor",
      },
      {
        name: "metric caption",
        className: "font_metric_caption",
        sample: "Lorem ipsum dolor",
      },
    ],
  },
];

function colorStyle(variable: string): CSSProperties {
  if (variable === "transparent") {
    return {
      backgroundColor: "transparent",
      backgroundImage:
        "linear-gradient(45deg, var(--color-border-default) 25%, transparent 25%), linear-gradient(-45deg, var(--color-border-default) 25%, transparent 25%), linear-gradient(45deg, transparent 75%, var(--color-border-default) 75%), linear-gradient(-45deg, transparent 75%, var(--color-border-default) 75%)",
      backgroundPosition: "0 0, 0 8px, 8px -8px, -8px 0",
      backgroundSize: "16px 16px",
    };
  }

  return { backgroundColor: `var(${variable})` };
}

function getNextCompositeIndex(
  currentIndex: number,
  itemCount: number,
  key: string,
): number | null {
  if (key === "ArrowRight" || key === "ArrowDown") {
    return (currentIndex + 1) % itemCount;
  }

  if (key === "ArrowLeft" || key === "ArrowUp") {
    return (currentIndex - 1 + itemCount) % itemCount;
  }

  if (key === "Home") {
    return 0;
  }

  if (key === "End") {
    return itemCount - 1;
  }

  return null;
}

function focusElementById(id: string) {
  window.requestAnimationFrame(() => {
    document.getElementById(id)?.focus();
  });
}

function TokenMapping({
  label,
  variable,
}: {
  label: "Semantic variable:" | "Light mode:" | "Dark mode:";
  variable: string;
}) {
  return (
    <div className="min-w-0">
      <dt className="font_metric_caption text-foreground-secondary">{label}</dt>
      <dd className="font_metric_caption break-all text-foreground-primary">
        {variable}
      </dd>
    </div>
  );
}

function ColorTokenCard({ token }: { token: ColorToken }) {
  return (
    <article className="overflow-hidden rounded-lg border border-border-default bg-surface-primary">
      <div
        className="h-20 border-b border-border-default"
        style={colorStyle(token.variable)}
      />
      <div className="space-y-3 p-4">
        <div>
          <h3 className="font_metric_label text-foreground-primary">
            {token.name}
          </h3>
        </div>
        <dl className="grid gap-1">
          <TokenMapping label="Semantic variable:" variable={token.variable} />
          <TokenMapping label="Light mode:" variable={token.light} />
          <TokenMapping label="Dark mode:" variable={token.dark} />
        </dl>
      </div>
    </article>
  );
}

function ColorGroups() {
  return (
    <div className="space-y-8">
      {semanticColorGroups.map((group) => (
        <div key={group.name}>
          <div className="mb-4">
            <h3 className="font_metric_label text-foreground-primary">
              {group.name}
            </h3>
            <p className="font_body_2 mt-1 text-foreground-secondary">
              {group.description}
            </p>
          </div>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-4">
            {group.tokens.map((token) => (
              <ColorTokenCard key={token.variable} token={token} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Section({
  children,
  title,
  subtitle,
}: {
  children: React.ReactNode;
  title: string;
  subtitle?: React.ReactNode;
}) {
  return (
    <section className="py-10">
      <div className="mx-auto px-5 sm:px-8">
        <div className="mb-6 max-w-3xl">
          <h2 className="font_header_3 text-foreground-primary">{title}</h2>
          {typeof subtitle === "string" ? (
            <p className="font_body_2 mt-2 text-foreground-secondary">
              {subtitle}
            </p>
          ) : subtitle ? (
            <div className="font_body_2 mt-2 space-y-3 text-foreground-secondary">
              {subtitle}
            </div>
          ) : null}
        </div>
        {children}
      </div>
    </section>
  );
}

function PathText({ children }: { children: React.ReactNode }) {
  return (
    <code className="font_jetbrains_mono rounded border border-border-default bg-surface-secondary px-1.5 py-0.5 text-foreground-primary">
      {children}
    </code>
  );
}

function ReferenceLink({
  children,
  href,
}: {
  children: React.ReactNode;
  href: string;
}) {
  return (
    <a
      className="text-foreground-primary underline decoration-border-active underline-offset-4 transition-colors hover:text-foreground-secondary"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {children}
    </a>
  );
}

function GuidelineDisclosure({
  children,
  title,
}: {
  children: React.ReactNode;
  title: string;
}) {
  return (
    <details className="mt-4 border-y border-border-default py-3">
      <summary className="font_metric_label cursor-pointer text-foreground-primary focus-visible:ring-2 focus-visible:ring-border-active">
        {title}
      </summary>
      <div className="mt-3 space-y-3 text-foreground-secondary">{children}</div>
    </details>
  );
}

function GuidelineLinks({
  links,
}: {
  links: Array<{ href: string; label: string }>;
}) {
  return (
    <ul className="space-y-1">
      {links.map((link) => (
        <li key={link.href}>
          <ReferenceLink href={link.href}>{link.label}</ReferenceLink>
        </li>
      ))}
    </ul>
  );
}

function SectionTabs({
  activeSection,
  onChange,
}: {
  activeSection: DesignSystemSection;
  onChange: (section: DesignSystemSection) => void;
}) {
  function handleTabKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    section: DesignSystemSection,
  ) {
    const currentIndex = sectionTabs.findIndex((tab) => tab.id === section);
    const nextIndex = getNextCompositeIndex(
      currentIndex,
      sectionTabs.length,
      event.key,
    );

    if (nextIndex === null) {
      return;
    }

    event.preventDefault();

    const nextSection = sectionTabs[nextIndex].id;
    onChange(nextSection);
    focusElementById(`design-system-tab-${nextSection}`);
  }

  return (
    <nav
      className="border-b border-border-default bg-surface-primary"
      aria-label="Design system sections"
    >
      <div className="mx-auto px-5 py-4 sm:px-8">
        <div
          className="flex w-full gap-[6px] overflow-x-auto rounded-lg border border-border-default bg-surface-secondary p-[6px] sm:w-fit"
          role="tablist"
        >
          {sectionTabs.map((tab) => {
            const isActive = activeSection === tab.id;

            return (
              <Button
                aria-controls={`design-system-panel-${tab.id}`}
                aria-selected={isActive}
                className={twMerge(
                  "font_metric_label h-9 shrink-0 cursor-pointer rounded-button px-4 text-foreground-primary transition-colors",
                  "hover:bg-surface-primary hover:text-foreground-primary",
                  "focus-visible:ring-2 focus-visible:ring-border-active",
                  isActive &&
                    "bg-accent text-accent-foreground hover:bg-accent-hover hover:text-accent-foreground",
                )}
                id={`design-system-tab-${tab.id}`}
                key={tab.id}
                onKeyDown={(event) => handleTabKeyDown(event, tab.id)}
                onClick={() => onChange(tab.id)}
                role="tab"
                tabIndex={isActive ? 0 : -1}
              >
                {tab.label}
              </Button>
            );
          })}
        </div>
      </div>
    </nav>
  );
}

function ComponentPreview() {
  const [exampleCheckboxChecked, setExampleCheckboxChecked] = useState(false);
  const [exampleTextValue, setExampleTextValue] = useState("");

  const secondaryButtonStates = [
    {
      label: "Normal",
      preview: <SecondaryButton>Lorem ipsum</SecondaryButton>,
    },
    {
      label: "Hover",
      preview: (
        <SecondaryButton className="border-border-hover bg-surface-secondary">
          Lorem ipsum
        </SecondaryButton>
      ),
    },
    {
      label: "Active",
      preview: (
        <SecondaryButton className="border-border-active bg-surface-inverse text-foreground-inverse">
          Lorem ipsum
        </SecondaryButton>
      ),
    },
    {
      label: "Focus",
      preview: (
        <SecondaryButton className="ring-2 ring-border-active">
          Lorem ipsum
        </SecondaryButton>
      ),
    },
    {
      label: "Disabled",
      preview: <SecondaryButton disabled>Lorem ipsum</SecondaryButton>,
    },
    {
      label: "Small",
      preview: <SecondaryButton size="sm">Lorem ipsum</SecondaryButton>,
    },
    {
      label: "Icon",
      preview: (
        <SecondaryButton ariaLabel="Lorem ipsum" size="icon">
          <Icon decorative icon="thumbsup" />
        </SecondaryButton>
      ),
    },
  ];

  const primaryButtonStates = [
    {
      label: "Normal",
      preview: <PrimaryButton>Lorem ipsum</PrimaryButton>,
    },
    {
      label: "Hover",
      preview: (
        <PrimaryButton className="border-border-hover">
          Lorem ipsum
        </PrimaryButton>
      ),
    },
    {
      label: "Active",
      preview: (
        <PrimaryButton className="border-border-active bg-surface-secondary text-foreground-primary">
          Lorem ipsum
        </PrimaryButton>
      ),
    },
    {
      label: "Focus",
      preview: (
        <PrimaryButton className="ring-2 ring-border-active">
          Lorem ipsum
        </PrimaryButton>
      ),
    },
    {
      label: "Disabled",
      preview: <PrimaryButton disabled>Lorem ipsum</PrimaryButton>,
    },
    {
      label: "Small",
      preview: <PrimaryButton size="sm">Lorem ipsum</PrimaryButton>,
    },
    {
      label: "Icon",
      preview: (
        <PrimaryButton ariaLabel="Lorem ipsum" size="icon">
          <Icon decorative icon="thumbsup" />
        </PrimaryButton>
      ),
    },
  ];

  const highlightButtonStates = [
    {
      label: "Normal",
      preview: <HighlightButton>Lorem ipsum</HighlightButton>,
    },
    {
      label: "Hover",
      preview: (
        <HighlightButton className="bg-accent-hover">
          Lorem ipsum
        </HighlightButton>
      ),
    },
    {
      label: "Active",
      preview: (
        <HighlightButton className="bg-accent-active text-foreground-inverse">
          Lorem ipsum
        </HighlightButton>
      ),
    },
    {
      label: "Focus",
      preview: (
        <HighlightButton className="ring-2 ring-border-active">
          Lorem ipsum
        </HighlightButton>
      ),
    },
    {
      label: "Disabled",
      preview: <HighlightButton disabled>Lorem ipsum</HighlightButton>,
    },
    {
      label: "Small",
      preview: <HighlightButton size="sm">Lorem ipsum</HighlightButton>,
    },
    {
      label: "Icon",
      preview: (
        <HighlightButton ariaLabel="Lorem ipsum" size="icon">
          <Icon decorative icon="thumbsup" />
        </HighlightButton>
      ),
    },
  ];

  const checkboxStates = [
    {
      label: "Inactive",
      preview: (
        <Checkbox
          checked={false}
          label="Lorem ipsum"
          labelClassName="text-foreground-primary"
        />
      ),
    },
    {
      label: "Hover",
      preview: (
        <Checkbox
          checked={false}
          className="border-border-hover bg-surface-secondary"
          label="Lorem ipsum"
          labelClassName="text-foreground-primary"
        />
      ),
    },
    {
      label: "Active",
      preview: (
        <Checkbox
          checked
          label="Lorem ipsum"
          labelClassName="text-foreground-primary"
        />
      ),
    },
    {
      label: "Active hover",
      preview: (
        <Checkbox
          checked
          className="border-accent-hover bg-accent-hover"
          label="Lorem ipsum"
          labelClassName="text-foreground-primary"
        />
      ),
    },
    {
      label: "Disabled",
      preview: (
        <Checkbox
          checked={false}
          disabled
          label="Lorem ipsum"
          labelClassName="text-foreground-primary"
        />
      ),
    },
  ];

  const textInputStates = [
    {
      label: "Normal",
      preview: <TextInput label="Glucose target" placeholder="Lorem ipsum" />,
    },
    {
      label: "Hover",
      preview: (
        <TextInput
          inputClassName="border-border-hover"
          label="Glucose target"
          placeholder="Lorem ipsum"
        />
      ),
    },
    {
      label: "Focus",
      preview: (
        <TextInput
          inputClassName="border-border-active ring-2 ring-border-active"
          label="Glucose target"
          placeholder="Lorem ipsum"
        />
      ),
    },
    {
      label: "Filled",
      preview: (
        <TextInput
          defaultValue="Lorem ipsum"
          label="Glucose target"
          placeholder="Lorem ipsum"
        />
      ),
    },
    {
      label: "Error",
      preview: (
        <TextInput
          errorMessage="Enter a value between 70 and 180 mg/dL."
          label="Glucose target"
          placeholder="Lorem ipsum"
        />
      ),
    },
    {
      label: "Disabled",
      preview: (
        <TextInput disabled label="Glucose target" placeholder="Lorem ipsum" />
      ),
    },
  ];

  const examples: ComponentExample[] = [
    {
      name: "SecondaryButton",
      description:
        "Muted secondary action styling built on Button and semantic tokens.",
      example: <SecondaryButton>Lorem ipsum</SecondaryButton>,
      preview: (
        <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(132px,1fr))] gap-3">
          {secondaryButtonStates.map((state) => (
            <div className="grid gap-2" key={state.label}>
              <span className="font_metric_caption text-foreground-secondary">
                {state.label}
              </span>
              <div className="flex min-h-10 items-center">{state.preview}</div>
            </div>
          ))}
        </div>
      ),
    },
    {
      name: "PrimaryButton",
      description:
        "Neutral primary action styling built on Button and semantic tokens.",
      example: <PrimaryButton>Lorem ipsum</PrimaryButton>,
      preview: (
        <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(132px,1fr))] gap-3">
          {primaryButtonStates.map((state) => (
            <div className="grid gap-2" key={state.label}>
              <span className="font_metric_caption text-foreground-secondary">
                {state.label}
              </span>
              <div className="flex min-h-10 items-center">{state.preview}</div>
            </div>
          ))}
        </div>
      ),
    },
    {
      name: "HighlightButton",
      description: "Accent action styling for high emphasis moments.",
      example: <HighlightButton>Lorem ipsum</HighlightButton>,
      preview: (
        <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(132px,1fr))] gap-3">
          {highlightButtonStates.map((state) => (
            <div className="grid gap-2" key={state.label}>
              <span className="font_metric_caption text-foreground-secondary">
                {state.label}
              </span>
              <div className="flex min-h-10 items-center">{state.preview}</div>
            </div>
          ))}
        </div>
      ),
    },
    {
      name: "TextInput",
      description:
        "Labelled text input with placeholder, error, and semantic token states.",
      example: (
        <TextInput
          label="Glucose target"
          onChange={(event) => setExampleTextValue(event.target.value)}
          placeholder="Lorem ipsum"
          value={exampleTextValue}
        />
      ),
      preview: (
        <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-3">
          {textInputStates.map((state) => (
            <div className="grid gap-2" key={state.label}>
              <span className="font_metric_caption text-foreground-secondary">
                {state.label}
              </span>
              {state.preview}
            </div>
          ))}
        </div>
      ),
    },
    {
      name: "Checkbox",
      description:
        "Labelled checkbox with inactive, hover, active, and disabled states.",
      example: (
        <Checkbox
          checked={exampleCheckboxChecked}
          label="Lorem ipsum"
          labelClassName="text-foreground-primary"
          onCheckedChange={setExampleCheckboxChecked}
        />
      ),
      preview: (
        <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-3">
          {checkboxStates.map((state) => (
            <div className="grid gap-2" key={state.label}>
              <span className="font_metric_caption text-foreground-secondary">
                {state.label}
              </span>
              <div className="flex min-h-10 items-center">{state.preview}</div>
            </div>
          ))}
        </div>
      ),
    },
    {
      name: "Accordion",
      description:
        "Accessible disclosure with controlled and uncontrolled state and a grid row transition.",
      preview: (
        <Accordion
          contentClassName="px-4 pb-4"
          trigger={
            <span className="font_body_2 text-foreground-primary">
              Connection details
            </span>
          }
          triggerClassName="px-4 py-3"
        >
          <div className="space-y-3 pt-4">
            {Array.from({ length: 8 }, (_, index) => (
              <p className="font_body_3 text-foreground-secondary" key={index}>
                Content row {index + 1} verifies that long panels animate
                without clipping.
              </p>
            ))}
          </div>
        </Accordion>
      ),
    },
    {
      name: "Icon",
      description: "Sprite based icon rendering with typed names.",
      example: <Icon icon="bell" />,
      preview: (
        <div className="flex items-center gap-3 text-foreground-primary">
          <Icon icon="bell" />
          <Icon icon="fork-knife" />
          <Icon icon="gear" />
          <Icon icon="person" />
        </div>
      ),
    },
    {
      name: "LumoseLoadingLogo",
      description:
        "Theme aware branded loading indicator for content loading states.",
      preview: (
        <LumoseLoadingLogo
          className="h-16 w-16"
          label="Loading design system preview"
        />
      ),
    },
  ];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {examples.map((example) => (
        <article
          className={twMerge(
            "grid gap-4 rounded-lg border border-border-default bg-surface-primary p-4",
            example.name === "PrimaryButton" ||
              example.name === "HighlightButton" ||
              example.name === "SecondaryButton" ||
              example.name === "TextInput" ||
              example.name === "Checkbox"
              ? "lg:grid-cols-[minmax(220px,0.35fr)_minmax(0,1fr)]"
              : "sm:grid-cols-[minmax(0,1fr)_minmax(220px,0.8fr)]",
          )}
          key={example.name}
        >
          <div>
            <h3 className="font_metric_label text-foreground-primary">
              {example.name}
            </h3>
            <p className="font_body_2 mt-1 text-foreground-secondary">
              {example.description}
            </p>
            {example.example ? (
              <div className="mt-4 flex min-h-10 items-center">
                {example.example}
              </div>
            ) : null}
          </div>
          <div className="flex min-h-24 items-center justify-start rounded-lg border border-border-default bg-surface-secondary p-4">
            {example.preview}
          </div>
        </article>
      ))}
    </div>
  );
}

function FontFamilies() {
  return (
    <dl className="mb-8 grid gap-3 sm:grid-cols-2 lg:w-2/3">
      {fontFamilies.map((fontFamily) => (
        <div
          className="rounded-lg border border-border-default bg-surface-primary p-4"
          key={fontFamily.className}
        >
          <dt className="font_metric_caption text-foreground-secondary">
            {fontFamily.label}
          </dt>
          <dd className="mt-1 flex flex-wrap items-baseline gap-2">
            <span className="font_body_2 text-foreground-primary">
              {fontFamily.name}
            </span>
            <code className="font_metric_caption rounded border border-border-default bg-surface-secondary px-2 py-1 text-foreground-primary">
              {fontFamily.className}
            </code>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function FontRoleCard({
  role,
  copiedClassName,
  onCopy,
}: {
  role: FontRole;
  copiedClassName: string | null;
  onCopy: (className: string) => Promise<void>;
}) {
  return (
    <article className="rounded-lg border border-border-default bg-surface-primary p-4 lg:w-1/3">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="font_metric_label capitalize text-foreground-primary">
            {role.name}
          </h4>
          <code className="font_metric_caption mt-1 block break-all text-foreground-secondary">
            {role.className}
          </code>
        </div>
        <CopyValueButton
          copiedValue={copiedClassName}
          label={`Copy ${role.className}`}
          onCopy={onCopy}
          value={role.className}
        />
      </div>
      <p className={twMerge(role.className, "text-foreground-primary")}>
        {role.sample}
      </p>
    </article>
  );
}

function CopyValueButton({
  copiedValue,
  label,
  onCopy,
  value,
}: {
  copiedValue: string | null;
  label: string;
  onCopy: (value: string) => Promise<void>;
  value: string;
}) {
  const isCopied = copiedValue === value;

  return (
    <div className="flex items-center gap-2">
      <span
        aria-live="polite"
        className={twMerge(
          "font_metric_caption min-w-14 text-signal-check-text transition-opacity",
          isCopied ? "opacity-100" : "opacity-0",
        )}
      >
        {isCopied ? "Copied" : ""}
      </span>
      <Button
        ariaLabel={label}
        className={twMerge(
          "inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-button border border-border-default bg-surface-secondary text-foreground-primary transition-colors hover:border-border-hover focus-visible:ring-2 focus-visible:ring-border-active",
          isCopied &&
            "border-signal-check-text text-signal-check-text hover:border-signal-check-text hover:text-signal-check-text",
        )}
        onClick={() => {
          void onCopy(value);
        }}
        title={label}
      >
        <Icon className="h-4 w-4" decorative icon="copy" />
      </Button>
    </div>
  );
}

function useCopiedValue() {
  const [copiedValue, setCopiedValue] = useState<string | null>(null);

  useEffect(() => {
    if (!copiedValue) {
      return;
    }

    const timeout = window.setTimeout(() => {
      setCopiedValue(null);
    }, 1600);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [copiedValue]);

  const copyValue = async (value: string) => {
    setCopiedValue(value);

    try {
      await writeTextToClipboard(value);
    } catch {
      return;
    }
  };

  return { copiedValue, copyValue };
}

function FontGrid() {
  const { copiedValue: copiedClassName, copyValue: copyClassName } =
    useCopiedValue();

  return (
    <div>
      <FontFamilies />
      <div className="space-y-8">
        {fontGroups.map((group) => (
          <div key={group.title}>
            <h3 className="font_header_4 mb-4 text-foreground-primary">
              {group.title}
            </h3>
            <div className="space-y-4">
              {group.roles.map((role) => (
                <FontRoleCard
                  copiedClassName={copiedClassName}
                  key={role.className}
                  onCopy={copyClassName}
                  role={role}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

async function writeTextToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall back for local browser contexts that expose Clipboard API but reject writes.
    }
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "");
  textArea.style.left = "-9999px";
  textArea.style.position = "absolute";
  textArea.style.top = "0";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  const copied = document.execCommand("copy");
  textArea.remove();

  if (!copied) {
    throw new Error("Copy command failed");
  }
}

function IconGrid() {
  const iconNames = useMemo(() => Object.keys(icons) as IconName[], []);
  const { copiedValue: copiedIconName, copyValue: copyIconName } =
    useCopiedValue();

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
      {iconNames.map((iconName) => (
        <article
          className="relative flex min-h-28 flex-col items-center justify-center gap-3 rounded-panel border border-border-default bg-surface-primary p-3 pt-12 text-center"
          key={iconName}
        >
          <div className="absolute right-2 top-2">
            <CopyValueButton
              copiedValue={copiedIconName}
              label={`Copy ${iconName}`}
              onCopy={copyIconName}
              value={iconName}
            />
          </div>
          <div className="grid min-h-12 w-full place-items-center">
            <Icon
              className="max-h-12 max-w-full text-foreground-primary"
              icon={iconName}
            />
          </div>
          <p className="font_metric_caption break-all text-foreground-secondary">
            {iconName}
          </p>
        </article>
      ))}
    </div>
  );
}

function GradientLogoGrid() {
  const logos = [
    {
      component: "TelegramLogo",
      preview: <TelegramLogo className="h-12 w-12" />,
    },
    {
      component: "LumoseLogoIcon",
      preview: <LumoseLogoIcon className="h-12 w-12" />,
    },
    {
      component: "LumoseLogoTextIcon",
      preview: <LumoseLogoTextIcon className="h-auto w-48 max-w-full" />,
    },
  ];

  return (
    <div className="mb-8">
      <h3 className="font_header_3 text-foreground-primary">
        Custom gradient logos
      </h3>
      <p className="font_body_2 mt-2 max-w-3xl text-foreground-secondary">
        Gradient assets own their SVG geometry and paint definitions inside a
        dedicated component. They are intentionally excluded from the sprite and
        base Icon primitive.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {logos.map((logo) => (
          <article
            className="flex min-h-32 flex-col items-center justify-center gap-4 rounded-panel border border-border-default bg-surface-primary p-4 text-center"
            key={logo.component}
          >
            <div className="grid min-h-14 w-full place-items-center text-foreground-primary">
              {logo.preview}
            </div>
            <code className="font_metric_caption text-foreground-secondary">
              {logo.component}
            </code>
          </article>
        ))}
      </div>
    </div>
  );
}

function AssetGrid() {
  const { copiedValue: copiedAssetPath, copyValue: copyAssetPath } =
    useCopiedValue();

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {imageAssets.map((asset) => (
        <article
          className="relative rounded-panel border border-border-default bg-surface-primary p-4 pt-12"
          key={asset.path}
        >
          <div className="absolute right-3 top-3">
            <CopyValueButton
              copiedValue={copiedAssetPath}
              label={`Copy ${asset.path}`}
              onCopy={copyAssetPath}
              value={asset.path}
            />
          </div>
          <div
            className={twMerge(
              "flex min-h-44 items-center justify-center overflow-hidden rounded-panel border border-border-default p-4",
              asset.previewClassName,
            )}
          >
            <Image
              alt={asset.label}
              className={twMerge(
                "object-contain",
                "previewAtNativeSize" in asset && asset.previewAtNativeSize
                  ? "h-auto w-auto"
                  : "h-32 w-full",
              )}
              height={asset.height}
              sizes="(min-width: 768px) 40vw, 80vw"
              src={asset.path}
              width={asset.width}
            />
          </div>
          <div className="mt-4">
            <p className="font_body_3 text-foreground-primary">{asset.label}</p>
            <p className="font_metric_caption mt-1 break-all text-foreground-secondary">
              {asset.path}
            </p>
            <p className="font_metric_caption mt-1 text-foreground-muted">
              {asset.width} × {asset.height} px
            </p>
          </div>
        </article>
      ))}
    </div>
  );
}

export function DesignSystemPage() {
  const [activeSection, setActiveSection] =
    useState<DesignSystemSection>("colors");

  return (
    <main
      className="min-h-screen bg-surface-page text-foreground-primary"
      style={designSystemFontStyle}
    >
      <header className="border-b border-border-default bg-surface-primary">
        <div className="mx-auto flex flex-col gap-5 px-5 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <div>
            <p className="font_metric_caption mb-2 text-foreground-secondary">
              GlycemicGPT web
            </p>
            <h1 className="font_header_1 text-foreground-primary">
              Design system
            </h1>
            <p className="font_body_1 mt-3 max-w-3xl text-foreground-secondary">
              Temporary inventory of the current UI foundation: semantic colors,
              sprite icons, image assets, base components, and shared font
              utilities.
            </p>
          </div>
          <ThemeSwitcher idPrefix="design-system-theme" />
        </div>
      </header>

      <SectionTabs activeSection={activeSection} onChange={setActiveSection} />

      <div
        aria-labelledby={`design-system-tab-${activeSection}`}
        id={`design-system-panel-${activeSection}`}
        role="tabpanel"
      >
        {activeSection === "colors" ? (
          <Section
            subtitle={
              <>
                <p>
                  Raw base colors live in{" "}
                  <PathText>apps/web/src/styles/config/colors.css</PathText>.
                  Those values are mapped to semantic roles in{" "}
                  <PathText>apps/web/src/styles/config/theme.css</PathText>,
                  where light and dark theme values are assigned. Components
                  then use Tailwind classes such as bg-surface-primary,
                  text-foreground-primary, border-border-default, and bg-accent.
                </p>
                <p>
                  Notice that the semantic color variables describe{" "}
                  <strong>intent</strong>, not the actual color. The benefit of
                  this approach is that we can change the color scheme entirely
                  without changing code inside any component.
                </p>
                <GuidelineDisclosure title="Color accessibility references">
                  <p>
                    Color pairings must follow the approved combinations in{" "}
                    <PathText>docs/dev/color-accessibility.md</PathText>. Normal
                    text needs AA contrast, non text UI needs enough contrast to
                    identify controls and state, and color must not be the only
                    way to communicate medical or product status.
                  </p>
                  <GuidelineLinks
                    links={[
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/conformance",
                        label: "WCAG 2.2 Conformance",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html",
                        label: "WCAG 1.4.3 Contrast Minimum",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html",
                        label: "WCAG 1.4.11 Non Text Contrast",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html",
                        label: "WCAG 1.4.1 Use of Color",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html",
                        label: "WCAG 2.4.7 Focus Visible",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html",
                        label: "WCAG 2.4.13 Focus Appearance",
                      },
                    ]}
                  />
                </GuidelineDisclosure>
              </>
            }
            title="Semantic Colors"
          >
            <ColorGroups />
          </Section>
        ) : null}

        {activeSection === "components" ? (
          <Section
            subtitle={
              <>
                Base primitives live in <PathText>apps/web/src/base</PathText>.
                Product components live in{" "}
                <PathText>apps/web/src/components</PathText> and compose base
                primitives with semantic classes. Base primitives stay visually
                neutral, though minimal structural classes are allowed. Larger
                screen level compositions will get their own compositions folder
                when repeated flows need a home.
                <GuidelineDisclosure title="Component accessibility references">
                  <p>
                    Components must support keyboard navigation, visible focus,
                    correct names, roles, values, and labels. Icon only controls
                    need an accessible name through text,{" "}
                    <PathText>aria-label</PathText>, or{" "}
                    <PathText>aria-labelledby</PathText>.
                  </p>
                  <GuidelineLinks
                    links={[
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html",
                        label: "WCAG 2.1.1 Keyboard",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html",
                        label: "WCAG 2.4.7 Focus Visible",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html",
                        label: "WCAG 4.1.2 Name, Role, Value",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html",
                        label: "WCAG 3.3.2 Labels or Instructions",
                      },
                    ]}
                  />
                </GuidelineDisclosure>
              </>
            }
            title="Components"
          >
            <ComponentPreview />
          </Section>
        ) : null}

        {activeSection === "icons" ? (
          <Section
            subtitle={
              <>
                <p>
                  Flat, theme-aware icons use the shared sprite in{" "}
                  <PathText>
                    apps/web/public/static_assets/iconSprite.svg
                  </PathText>
                  . Each symbol is registered through typed icon config and
                  rendered with the base Icon primitive in{" "}
                  <PathText>apps/web/src/base/Icon</PathText>.
                </p>
                <p>
                  The implementation uses an SVG sprite pattern for icon
                  optimization.
                  <span className="mt-1 block">
                    Reference:{" "}
                    <ReferenceLink href="https://benadam.me/thoughts/react-svg-sprites/">
                      React SVG sprites
                    </ReferenceLink>
                    .
                  </span>
                </p>
                <div>
                  <p>Icon sources used in this project:</p>
                  <ul className="mt-2 space-y-1">
                    <li>
                      <ReferenceLink href="https://www.figma.com/community/file/809920999413919915">
                        Octicons, GitHub icon set
                      </ReferenceLink>
                    </li>
                    <li>
                      <ReferenceLink href="https://www.streamlinehq.com/icons">
                        Streamline Icons
                      </ReferenceLink>
                    </li>
                  </ul>
                </div>
                <GuidelineDisclosure title="Icon accessibility references">
                  <p>
                    The base Icon component supports decorative icons through
                    the <PathText>decorative</PathText> prop. Meaningful icons
                    use the configured title by default, or an explicit{" "}
                    <PathText>title</PathText> override when the visible context
                    needs a more specific accessible name.
                  </p>
                  <GuidelineLinks
                    links={[
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html",
                        label: "WCAG 1.1.1 Non Text Content",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html",
                        label: "WCAG 4.1.2 Name, Role, Value",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html",
                        label: "WCAG 1.4.11 Non Text Contrast",
                      },
                    ]}
                  />
                </GuidelineDisclosure>
              </>
            }
            title="Icons"
          >
            <GradientLogoGrid />
            <IconGrid />
          </Section>
        ) : null}

        {activeSection === "assets" ? (
          <Section
            subtitle={
              <p>
                PNG and JPG assets served from the web public directory. The
                inventory includes app icons, favicons, and exported Lumose logo
                variants.
              </p>
            }
            title="Assets"
          >
            <AssetGrid />
          </Section>
        ) : null}

        {activeSection === "fonts" ? (
          <Section
            subtitle={
              <>
                <p>
                  Typography is exposed as Tailwind utility classes like
                  font_header_1 and font_body_2. They are defined in{" "}
                  <PathText>apps/web/src/styles/config/fonts.css</PathText> and
                  registered with the local twMerge wrapper, so components can
                  use one role class instead of repeating font family, size,
                  weight, line height, and spacing.
                </p>
                <p>
                  Notice that font classes are responsive by default. They
                  change size between mobile and desktop without adding
                  breakpoint classes inside components.
                </p>
                <GuidelineDisclosure title="Font accessibility references">
                  <p>
                    Font utilities use <PathText>rem</PathText> units, so text
                    scales with the user browser text size setting. Components
                    should not lock important text to fixed pixel sizes or
                    depend on viewport based font scaling.
                  </p>
                  <GuidelineLinks
                    links={[
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html",
                        label: "WCAG 1.4.4 Resize Text",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html",
                        label: "WCAG 1.4.12 Text Spacing",
                      },
                      {
                        href: "https://www.w3.org/WAI/WCAG22/Understanding/reflow.html",
                        label: "WCAG 1.4.10 Reflow",
                      },
                    ]}
                  />
                </GuidelineDisclosure>
              </>
            }
            title="Fonts"
          >
            <FontGrid />
          </Section>
        ) : null}
      </div>
    </main>
  );
}
