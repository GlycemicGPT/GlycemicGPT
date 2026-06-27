/**
 * Tests for the GlucoseHero component.
 *
 * Story 4.2: GlucoseHero Component
 */

import { render, screen } from "@testing-library/react";
import {
  GlucoseHero,
  classifyGlucose,
  parseLoopState,
  prettySourceName,
  shouldPulse,
  GLUCOSE_THRESHOLDS,
  type TrendDirection,
} from "../../../src/components/dashboard/glucose-hero";
import GlucoseHeroDefault from "../../../src/components/dashboard/glucose-hero";
import { formatGlucose } from "@/lib/glucose-units";

// Mock framer-motion to avoid animation issues in tests
const mockUseReducedMotion = jest.fn(() => false);

jest.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      className,
      ...props
    }: {
      children: React.ReactNode;
      className?: string;
      [key: string]: unknown;
    }) => (
      <div className={className} {...props}>
        {children}
      </div>
    ),
  },
  useReducedMotion: () => mockUseReducedMotion(),
}));

// Reset mock before each test
beforeEach(() => {
  mockUseReducedMotion.mockReturnValue(false);
});

describe("GLUCOSE_THRESHOLDS", () => {
  it("exports expected threshold values", () => {
    expect(GLUCOSE_THRESHOLDS.URGENT_LOW).toBe(55);
    expect(GLUCOSE_THRESHOLDS.LOW).toBe(70);
    expect(GLUCOSE_THRESHOLDS.HIGH).toBe(180);
    expect(GLUCOSE_THRESHOLDS.URGENT_HIGH).toBe(250);
  });
});

describe("classifyGlucose", () => {
  it('returns "urgentLow" for glucose < 55', () => {
    expect(classifyGlucose(54)).toBe("urgentLow");
    expect(classifyGlucose(40)).toBe("urgentLow");
    expect(classifyGlucose(0)).toBe("urgentLow");
  });

  it('returns "low" for glucose 55-69', () => {
    expect(classifyGlucose(55)).toBe("low");
    expect(classifyGlucose(60)).toBe("low");
    expect(classifyGlucose(69)).toBe("low");
  });

  it('returns "inRange" for glucose 70-180', () => {
    expect(classifyGlucose(70)).toBe("inRange");
    expect(classifyGlucose(120)).toBe("inRange");
    expect(classifyGlucose(180)).toBe("inRange");
  });

  it('returns "high" for glucose 181-250', () => {
    expect(classifyGlucose(181)).toBe("high");
    expect(classifyGlucose(200)).toBe("high");
    expect(classifyGlucose(250)).toBe("high");
  });

  it('returns "urgentHigh" for glucose > 250', () => {
    expect(classifyGlucose(251)).toBe("urgentHigh");
    expect(classifyGlucose(300)).toBe("urgentHigh");
    expect(classifyGlucose(400)).toBe("urgentHigh");
  });

  it('returns "inRange" for null glucose', () => {
    expect(classifyGlucose(null)).toBe("inRange");
  });
});

describe("band stays mg/dL regardless of display unit", () => {
  // The range classifier takes NO unit argument: it bands a stored mg/dL value
  // and the user's display preference cannot reach it. These values are chosen
  // to fall in the SAME band on the web, phone (glucoseColor), and watch
  // (bgColor) so a reading can never read "low" on one surface and "in range"
  // on another. (55 and the threshold edges are deliberately avoided because the
  // surfaces differ by one mg/dL on the boundary `<` vs `<=`.)
  const BANDS: Array<[number, ReturnType<typeof classifyGlucose>]> = [
    [40, "urgentLow"],
    [65, "low"],
    [120, "inRange"],
    [200, "high"],
    [300, "urgentHigh"],
  ];

  it.each(BANDS)("classifies %d mg/dL as %s", (mgdl, band) => {
    expect(classifyGlucose(mgdl)).toBe(band);
  });

  it("classifies the raw mg/dL value even though the displayed number changes", () => {
    // 65 mg/dL displays as "65" or "3.6" depending on the unit, but it is a
    // "low" reading in BOTH -- the safety band reads the stored value, never the
    // displayed one.
    expect(formatGlucose(65, "mgdl")).toBe("65");
    expect(formatGlucose(65, "mmol")).toBe("3.6");
    expect(classifyGlucose(65)).toBe("low");
  });
});

describe("shouldPulse", () => {
  it('returns "strong" for urgentLow', () => {
    expect(shouldPulse("urgentLow")).toBe("strong");
  });

  it('returns "strong" for urgentHigh', () => {
    expect(shouldPulse("urgentHigh")).toBe("strong");
  });

  it('returns "subtle" for low', () => {
    expect(shouldPulse("low")).toBe("subtle");
  });

  it('returns "subtle" for high', () => {
    expect(shouldPulse("high")).toBe("subtle");
  });

  it("returns null for inRange", () => {
    expect(shouldPulse("inRange")).toBeNull();
  });
});

describe("GlucoseHero", () => {
  const defaultProps = {
    value: 142,
    trend: "Stable" as TrendDirection,
    iob: 2.4,
    basalRate: 1.5,
    batteryPct: 85,
    reservoirUnits: 180,
  };

  describe("glucose value display", () => {
    it("displays glucose value in large text", () => {
      render(<GlucoseHero {...defaultProps} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveTextContent("142");
      expect(glucoseValue).toHaveClass("text-5xl", "sm:text-7xl", "font-bold");
    });

    it('displays "--" when value is null', () => {
      render(<GlucoseHero {...defaultProps} value={null} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveTextContent("--");
    });

    it("rounds decimal values to integers", () => {
      render(<GlucoseHero {...defaultProps} value={142.7} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveTextContent("143");
    });
  });

  describe("unit label display", () => {
    it('displays default unit "mg/dL"', () => {
      render(<GlucoseHero {...defaultProps} />);

      expect(screen.getByTestId("glucose-unit")).toHaveTextContent("mg/dL");
    });

    it("displays the mmol/L label and converts the value when unit=mmol", () => {
      // value stays mg/dL; display converts (180 -> 10.0).
      render(<GlucoseHero {...defaultProps} value={180} unit="mmol" />);

      expect(screen.getByTestId("glucose-unit")).toHaveTextContent("mmol/L");
      expect(screen.getByTestId("glucose-value")).toHaveTextContent("10.0");
    });

    it("shows 1-decimal mmol for the clinical anchor 70 -> 3.9", () => {
      render(<GlucoseHero {...defaultProps} value={70} unit="mmol" />);

      expect(screen.getByTestId("glucose-value")).toHaveTextContent("3.9");
    });
  });

  describe("trend arrow display", () => {
    it.each([
      ["RisingFast", "↑↑"],
      ["Rising", "↗"],
      ["Stable", "→"],
      ["Falling", "↘"],
      ["FallingFast", "↓↓"],
      ["Unknown", "?"],
    ] as const)(
      "displays correct arrow for trend %s",
      (trend: TrendDirection, expectedArrow: string) => {
        render(<GlucoseHero {...defaultProps} trend={trend} />);

        const trendArrow = screen.getByTestId("trend-arrow");
        expect(trendArrow).toHaveTextContent(expectedArrow);
      }
    );

    it.each([
      ["RisingFast", "↑↑"],
      ["Falling", "↘"],
      ["Stable", "→"],
    ] as const)(
      "renders the same %s arrow whether the unit is mg/dL or mmol/L",
      (trend: TrendDirection, expectedArrow: string) => {
        // The arrow comes from the backend trend direction, not the glucose
        // unit -- so switching units changes the value (180 -> 10.0) but never
        // flips the arrow.
        const { unmount } = render(
          <GlucoseHero {...defaultProps} value={180} trend={trend} unit="mgdl" />
        );
        expect(screen.getByTestId("trend-arrow")).toHaveTextContent(expectedArrow);
        expect(screen.getByTestId("glucose-value")).toHaveTextContent("180");
        unmount();

        render(
          <GlucoseHero {...defaultProps} value={180} trend={trend} unit="mmol" />
        );
        expect(screen.getByTestId("trend-arrow")).toHaveTextContent(expectedArrow);
        expect(screen.getByTestId("glucose-value")).toHaveTextContent("10.0");
      }
    );
  });

  describe("secondary metrics display", () => {
    it("displays IoB value with unit", () => {
      render(<GlucoseHero {...defaultProps} iob={2.4} />);

      expect(screen.getByTestId("iob-value")).toHaveTextContent("2.40u");
    });

    it("displays basal rate with unit", () => {
      render(<GlucoseHero {...defaultProps} basalRate={1.5} />);

      expect(screen.getByTestId("basal-value")).toHaveTextContent("1.50 u/hr");
    });

    it("displays battery percentage", () => {
      render(<GlucoseHero {...defaultProps} batteryPct={85} />);

      expect(screen.getByTestId("battery-value")).toHaveTextContent("85%");
    });

    it("displays reservoir units", () => {
      render(<GlucoseHero {...defaultProps} reservoirUnits={180} />);

      expect(screen.getByTestId("reservoir-value")).toHaveTextContent("180u");
    });

    it('displays "--" for null IoB', () => {
      render(<GlucoseHero {...defaultProps} iob={null} />);

      expect(screen.getByTestId("iob-value")).toHaveTextContent("--");
    });

    it('displays "--" for null basal rate', () => {
      render(<GlucoseHero {...defaultProps} basalRate={null} />);

      expect(screen.getByTestId("basal-value")).toHaveTextContent("--");
    });

    it('displays "--" for null battery', () => {
      render(<GlucoseHero {...defaultProps} batteryPct={null} />);

      expect(screen.getByTestId("battery-value")).toHaveTextContent("--");
    });

    it('displays "--" for null reservoir', () => {
      render(<GlucoseHero {...defaultProps} reservoirUnits={null} />);

      expect(screen.getByTestId("reservoir-value")).toHaveTextContent("--");
    });

    it("formats IoB to 2 decimal places", () => {
      render(<GlucoseHero {...defaultProps} iob={2.456} />);

      expect(screen.getByTestId("iob-value")).toHaveTextContent("2.46u");
    });

    it("formats basal rate to 2 decimal places", () => {
      render(<GlucoseHero {...defaultProps} basalRate={1.234} />);

      expect(screen.getByTestId("basal-value")).toHaveTextContent("1.23 u/hr");
    });
  });

  describe("color coding by glucose range", () => {
    it("uses green styling for in-range glucose (70-180)", () => {
      render(<GlucoseHero {...defaultProps} value={120} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveClass("text-green-400");
    });

    it("uses amber styling for low warning glucose (55-70)", () => {
      render(<GlucoseHero {...defaultProps} value={65} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveClass("text-amber-400");
    });

    it("uses red styling for urgent low glucose (<55)", () => {
      render(<GlucoseHero {...defaultProps} value={50} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveClass("text-red-500");
    });

    it("uses amber styling for high warning glucose (180-250)", () => {
      render(<GlucoseHero {...defaultProps} value={200} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveClass("text-amber-400");
    });

    it("uses red styling for urgent high glucose (>250)", () => {
      render(<GlucoseHero {...defaultProps} value={280} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveClass("text-red-500");
    });

    it("trend arrow inherits glucose range color", () => {
      render(<GlucoseHero {...defaultProps} value={120} />);

      const trendArrow = screen.getByTestId("trend-arrow");
      expect(trendArrow).toHaveClass("text-green-400");
    });

    it("trend arrow uses same color as urgent glucose value", () => {
      render(<GlucoseHero {...defaultProps} value={280} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      const trendArrow = screen.getByTestId("trend-arrow");
      expect(glucoseValue).toHaveClass("text-red-500");
      expect(trendArrow).toHaveClass("text-red-500");
    });
  });

  describe("accessibility", () => {
    it("has region role with appropriate label", () => {
      render(<GlucoseHero {...defaultProps} />);

      expect(
        screen.getByRole("region", { name: "Current glucose reading" })
      ).toBeInTheDocument();
    });

    it("provides aria-label with glucose reading details", () => {
      render(<GlucoseHero {...defaultProps} value={142} trend="Stable" />);

      const glucoseValue = screen.getByTestId("glucose-value");
      // Story 4.6: Enhanced accessible announcement format
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        "Glucose 142 milligrams per deciliter, stable, in target range"
      );
    });

    it("provides appropriate aria-label when value is null", () => {
      render(<GlucoseHero {...defaultProps} value={null} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      // Story 4.6: Enhanced accessible announcement format
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        "Glucose reading unavailable"
      );
    });

    it("has aria-live polite for glucose updates", () => {
      render(<GlucoseHero {...defaultProps} />);

      // The parent container of the glucose value should have aria-live
      const container = screen.getByTestId("glucose-value").parentElement;
      expect(container).toHaveAttribute("aria-live", "polite");
    });

    it("hides trend arrow from screen readers", () => {
      render(<GlucoseHero {...defaultProps} />);

      const trendArrow = screen.getByTestId("trend-arrow");
      expect(trendArrow).toHaveAttribute("aria-hidden", "true");
    });
  });

  describe("reduced motion support", () => {
    it("disables pulse animation when prefers-reduced-motion is enabled", () => {
      mockUseReducedMotion.mockReturnValue(true);

      // Render with urgent low (would normally have strong pulse)
      render(<GlucoseHero {...defaultProps} value={50} />);

      // Component should render correctly in reduced motion mode
      expect(screen.getByTestId("glucose-value")).toBeInTheDocument();
      expect(screen.getByTestId("glucose-value")).toHaveTextContent("50");
    });

    it("component renders normally when motion is allowed", () => {
      mockUseReducedMotion.mockReturnValue(false);

      render(<GlucoseHero {...defaultProps} value={50} />);

      expect(screen.getByTestId("glucose-value")).toBeInTheDocument();
    });
  });

  describe("stale data indicator", () => {
    it("shows stale warning when isStale is true", () => {
      render(<GlucoseHero {...defaultProps} isStale={true} minutesAgo={15} />);

      expect(screen.getByTestId("stale-warning")).toBeInTheDocument();
      expect(screen.getByText(/Data is 15\+ minutes old/)).toBeInTheDocument();
    });

    it("does not show stale warning when isStale is false", () => {
      render(<GlucoseHero {...defaultProps} isStale={false} minutesAgo={2} />);

      expect(screen.queryByTestId("stale-warning")).not.toBeInTheDocument();
    });

    it("uses default minutes when minutesAgo is not provided", () => {
      render(<GlucoseHero {...defaultProps} isStale={true} />);

      expect(screen.getByText(/Data is 10\+ minutes old/)).toBeInTheDocument();
    });

    it("stale warning has alert role for screen readers", () => {
      render(<GlucoseHero {...defaultProps} isStale={true} minutesAgo={15} />);

      expect(screen.getByTestId("stale-warning")).toHaveAttribute("role", "alert");
    });
  });

  describe("loading state", () => {
    it("shows loading skeleton when isLoading is true", () => {
      render(<GlucoseHero {...defaultProps} isLoading={true} />);

      expect(
        screen.getByRole("region", { name: "Loading glucose reading" })
      ).toBeInTheDocument();
    });

    it("has aria-busy when loading", () => {
      render(<GlucoseHero {...defaultProps} isLoading={true} />);

      expect(
        screen.getByRole("region", { name: "Loading glucose reading" })
      ).toHaveAttribute("aria-busy", "true");
    });

    it("does not show glucose value when loading", () => {
      render(<GlucoseHero {...defaultProps} isLoading={true} />);

      expect(screen.queryByTestId("glucose-value")).not.toBeInTheDocument();
    });

    it("shows normal content when isLoading is false", () => {
      render(<GlucoseHero {...defaultProps} isLoading={false} />);

      expect(screen.getByTestId("glucose-value")).toBeInTheDocument();
    });
  });

  describe("defensive handling", () => {
    it("treats NaN glucose as null", () => {
      render(<GlucoseHero {...defaultProps} value={NaN} />);

      expect(screen.getByTestId("glucose-value")).toHaveTextContent("--");
    });

    it("treats negative glucose as null", () => {
      render(<GlucoseHero {...defaultProps} value={-50} />);

      expect(screen.getByTestId("glucose-value")).toHaveTextContent("--");
    });

    it("treats Infinity as null", () => {
      render(<GlucoseHero {...defaultProps} value={Infinity} />);

      expect(screen.getByTestId("glucose-value")).toHaveTextContent("--");
    });

    it("treats negative Infinity as null", () => {
      render(<GlucoseHero {...defaultProps} value={-Infinity} />);

      expect(screen.getByTestId("glucose-value")).toHaveTextContent("--");
    });

    it("treats NaN IoB as null", () => {
      render(<GlucoseHero {...defaultProps} iob={NaN} />);

      expect(screen.getByTestId("iob-value")).toHaveTextContent("--");
    });

    it("treats NaN battery as null", () => {
      render(<GlucoseHero {...defaultProps} batteryPct={NaN} />);

      expect(screen.getByTestId("battery-value")).toHaveTextContent("--");
    });

    it("treats negative reservoir as null", () => {
      render(<GlucoseHero {...defaultProps} reservoirUnits={-10} />);

      expect(screen.getByTestId("reservoir-value")).toHaveTextContent("--");
    });

    it("allows negative IoB (rare but possible)", () => {
      render(<GlucoseHero {...defaultProps} iob={-0.5} />);

      expect(screen.getByTestId("iob-value")).toHaveTextContent("-0.50u");
    });
  });

  describe("exports", () => {
    it("default export works", () => {
      render(<GlucoseHeroDefault {...defaultProps} />);

      expect(screen.getByTestId("glucose-value")).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Story 43.12 PR 6 -- closed-loop runtime surfaces
  // -------------------------------------------------------------------------

  describe("loop status badge (PR 6)", () => {
    it("renders nothing when loopStatus is null", () => {
      render(<GlucoseHero {...defaultProps} loopStatus={null} />);
      expect(screen.queryByTestId("loop-status-badge")).not.toBeInTheDocument();
    });

    it("renders 'Looping' for state='looping'", () => {
      render(
        <GlucoseHero
          {...defaultProps}
          loopStatus={{
            state: "looping",
            source: "loop",
            issuedAt: "2026-05-13T14:00:00Z",
          }}
        />
      );
      const badge = screen.getByTestId("loop-status-badge");
      expect(badge).toHaveAttribute("data-state", "looping");
      expect(badge).toHaveTextContent("Looping");
      expect(badge).toHaveTextContent("Loop");
    });

    it("renders 'Not looping' for state='not_looping'", () => {
      render(
        <GlucoseHero
          {...defaultProps}
          loopStatus={{
            state: "not_looping",
            source: "aaps",
            issuedAt: "2026-05-13T14:00:00Z",
          }}
        />
      );
      const badge = screen.getByTestId("loop-status-badge");
      expect(badge).toHaveAttribute("data-state", "not_looping");
      expect(badge).toHaveTextContent("Not looping");
      expect(badge).toHaveTextContent("AAPS");
    });

    it("renders 'Loop failed' with failure reason in tooltip", () => {
      render(
        <GlucoseHero
          {...defaultProps}
          loopStatus={{
            state: "failed",
            source: "loop",
            issuedAt: "2026-05-13T14:00:00Z",
            failureReason: "Glucose data is unavailable",
          }}
        />
      );
      const badge = screen.getByTestId("loop-status-badge");
      expect(badge).toHaveAttribute("data-state", "failed");
      expect(badge).toHaveTextContent("Loop failed");
      // Failure reason flows into the title tooltip (visible on hover);
      // ariaLabel describes the state separately for screen readers.
      expect(badge).toHaveAttribute(
        "title",
        "Loop: Glucose data is unavailable"
      );
    });

    it("displays known source names with proper casing", () => {
      const sources: Array<[string, string]> = [
        ["loop", "Loop"],
        ["aaps", "AAPS"],
        ["trio", "Trio"],
        ["oref0", "oref0"],
        ["iaps", "iAPS"],
      ];
      for (const [source, display] of sources) {
        const { unmount } = render(
          <GlucoseHero
            {...defaultProps}
            loopStatus={{
              state: "looping",
              source,
              issuedAt: "2026-05-13T14:00:00Z",
            }}
          />
        );
        expect(screen.getByTestId("loop-status-badge")).toHaveTextContent(
          display
        );
        unmount();
      }
    });
  });

  describe("override row (PR 6)", () => {
    it("renders nothing when override is null", () => {
      render(<GlucoseHero {...defaultProps} override={null} />);
      expect(screen.queryByTestId("override-row")).not.toBeInTheDocument();
    });

    it("renders override name and time remaining", () => {
      // Pin "now" to one minute past the override start so the
      // duration math is stable across CI clocks.
      const now = new Date("2026-05-13T14:01:00Z");
      jest.useFakeTimers();
      jest.setSystemTime(now);
      try {
        render(
          <GlucoseHero
            {...defaultProps}
            override={{
              name: "Pre-meal",
              startedAt: "2026-05-13T14:00:00Z",
              endsAt: "2026-05-13T14:30:00Z",
              multiplier: 0.7,
            }}
          />
        );
        const row = screen.getByTestId("override-row");
        expect(row).toHaveTextContent("Override: Pre-meal");
        // 29 minutes remaining (rounded)
        expect(row).toHaveTextContent("ends in 29 min");
      } finally {
        jest.useRealTimers();
      }
    });

    it("renders 'ongoing' for indefinite overrides (endsAt=null)", () => {
      render(
        <GlucoseHero
          {...defaultProps}
          override={{
            name: "Workout",
            startedAt: "2026-05-13T14:00:00Z",
            endsAt: null,
          }}
        />
      );
      expect(screen.getByTestId("override-row")).toHaveTextContent("ongoing");
    });

    it("renders 'ongoing' for past-end overrides (clock skew safety)", () => {
      // If a stale snapshot still has `active: true` but the end time
      // is already in the past (clock skew across the user's devices),
      // the formatter returns null and we fall back to "ongoing"
      // rather than rendering "ends in -5 min".
      const now = new Date("2026-05-13T15:00:00Z");
      jest.useFakeTimers();
      jest.setSystemTime(now);
      try {
        render(
          <GlucoseHero
            {...defaultProps}
            override={{
              name: "Workout",
              startedAt: "2026-05-13T13:00:00Z",
              endsAt: "2026-05-13T14:00:00Z",
            }}
          />
        );
        expect(screen.getByTestId("override-row")).toHaveTextContent("ongoing");
      } finally {
        jest.useRealTimers();
      }
    });

    it("renders hours+minutes for long overrides", () => {
      const now = new Date("2026-05-13T14:00:00Z");
      jest.useFakeTimers();
      jest.setSystemTime(now);
      try {
        render(
          <GlucoseHero
            {...defaultProps}
            override={{
              name: "Sleep",
              startedAt: "2026-05-13T14:00:00Z",
              endsAt: "2026-05-13T16:30:00Z",
            }}
          />
        );
        expect(screen.getByTestId("override-row")).toHaveTextContent(
          "ends in 2h 30m"
        );
      } finally {
        jest.useRealTimers();
      }
    });
  });

  describe("COB metric (PR 6)", () => {
    it("renders nothing when cobGrams is null", () => {
      render(<GlucoseHero {...defaultProps} cobGrams={null} />);
      expect(screen.queryByTestId("cob-value")).not.toBeInTheDocument();
    });

    it("renders nothing when cobGrams is undefined (back-compat)", () => {
      render(<GlucoseHero {...defaultProps} />);
      expect(screen.queryByTestId("cob-value")).not.toBeInTheDocument();
    });

    it("renders rounded grams when cobGrams is present", () => {
      render(<GlucoseHero {...defaultProps} cobGrams={24.4} />);
      expect(screen.getByTestId("cob-value")).toHaveTextContent("24g");
    });

    it("renders zero cleanly", () => {
      // Zero is a valid COB reading ("no carbs absorbing right now");
      // distinct from "no data" which is null/undefined.
      render(<GlucoseHero {...defaultProps} cobGrams={0} />);
      expect(screen.getByTestId("cob-value")).toHaveTextContent("0g");
    });

    it("rejects negative cob via sanitizer", () => {
      // Carbs grams can't be negative; defensive sanitization should
      // hide the column rather than render -5g.
      render(<GlucoseHero {...defaultProps} cobGrams={-5} />);
      expect(screen.queryByTestId("cob-value")).not.toBeInTheDocument();
    });
  });
});


describe("parseLoopState (PR 6 adversarial fix)", () => {
  it("accepts canonical loop states", () => {
    expect(parseLoopState("looping")).toBe("looping");
    expect(parseLoopState("not_looping")).toBe("not_looping");
    expect(parseLoopState("failed")).toBe("failed");
  });

  it("returns null for unknown states", () => {
    // Future-proofing -- if the backend ever returns "warming_up"
    // or "unknown", the page-level mapper will short-circuit to
    // null rather than letting `LOOP_STATE_STYLE[unknown]` crash.
    expect(parseLoopState("warming_up")).toBeNull();
    expect(parseLoopState("LOOPING")).toBeNull(); // case-sensitive
    expect(parseLoopState("")).toBeNull();
  });
});

describe("prettySourceName (PR 6 adversarial fix)", () => {
  it("maps known sources to friendly display names", () => {
    expect(prettySourceName("loop")).toBe("Loop");
    expect(prettySourceName("aaps")).toBe("AAPS");
    expect(prettySourceName("trio")).toBe("Trio");
    expect(prettySourceName("oref0")).toBe("oref0");
    expect(prettySourceName("iaps")).toBe("iAPS");
  });

  it("falls back to a generic label for unknown sources", () => {
    // Defensive: an unrecognized string from the backend renders
    // as "Closed loop" rather than echoing whatever value the
    // server sent. Backend contract is bounded today; this is
    // forward-protection.
    expect(prettySourceName("future-engine")).toBe("Closed loop");
    expect(prettySourceName("")).toBe("Closed loop");
  });

  it("treats casing strictly (parity with parseLoopState)", () => {
    // Backend's Pydantic `Literal` emits lowercase canonical values
    // and this is mirrored on the API type. Mixed-case input is a
    // contract drift, not something to paper over.
    expect(prettySourceName("LOOP")).toBe("Closed loop");
    expect(prettySourceName("Loop")).toBe("Closed loop");
  });
});
