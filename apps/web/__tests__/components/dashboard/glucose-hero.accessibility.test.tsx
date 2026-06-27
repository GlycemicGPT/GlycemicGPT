/**
 * GlucoseHero Accessibility Tests
 *
 * Story 4.6: Dashboard Accessibility
 * Tests for screen reader announcements, keyboard navigation,
 * and WCAG compliance.
 */

import { render, screen } from "@testing-library/react";

import {
  GlucoseHero,
  buildGlucoseAnnouncement,
  getRangeStatus,
  isUrgentState,
  classifyGlucose,
} from "@/components/dashboard/glucose-hero";

describe("GlucoseHero Accessibility", () => {
  describe("Screen Reader Announcements", () => {
    it("announces glucose with value, trend, and range status", () => {
      render(<GlucoseHero value={142} trend="Falling" iob={2.5} basalRate={1.5} batteryPct={85} reservoirUnits={180} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        expect.stringMatching(/glucose 142 milligrams per deciliter/i)
      );
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        expect.stringMatching(/in target range/i)
      );
    });

    it("has exact announcement format", () => {
      // Pattern: "Glucose {value} milligrams per deciliter, {trend}, {range status}"
      // Example: "Glucose 142 milligrams per deciliter, falling, in target range"
      render(<GlucoseHero value={142} trend="Falling" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        "Glucose 142 milligrams per deciliter, falling, in target range"
      );
    });

    it("announces low glucose correctly", () => {
      render(<GlucoseHero value={65} trend="Falling" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        expect.stringMatching(/below target/i)
      );
    });

    it("announces urgent low glucose correctly", () => {
      render(<GlucoseHero value={50} trend="FallingFast" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        expect.stringMatching(/dangerously low/i)
      );
    });

    it("announces high glucose correctly", () => {
      render(<GlucoseHero value={200} trend="Rising" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        expect.stringMatching(/above target/i)
      );
    });

    it("announces urgent high glucose correctly", () => {
      render(<GlucoseHero value={280} trend="RisingFast" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        expect.stringMatching(/dangerously high/i)
      );
    });

    it("announces unavailable glucose correctly", () => {
      render(<GlucoseHero value={null} trend="Unknown" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const glucoseValue = screen.getByTestId("glucose-value");
      expect(glucoseValue).toHaveAttribute(
        "aria-label",
        "Glucose reading unavailable"
      );
    });
  });

  describe("Aria-live Priority", () => {
    it("uses polite aria-live for in-range glucose", () => {
      render(<GlucoseHero value={120} trend="Stable" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const liveRegion = screen.getByRole("region").querySelector("[aria-live]");
      expect(liveRegion).toHaveAttribute("aria-live", "polite");
    });

    it("uses assertive aria-live for urgent low glucose", () => {
      render(<GlucoseHero value={50} trend="FallingFast" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const liveRegion = screen.getByRole("region").querySelector("[aria-live]");
      expect(liveRegion).toHaveAttribute("aria-live", "assertive");
    });

    it("uses assertive aria-live for urgent high glucose", () => {
      render(<GlucoseHero value={280} trend="RisingFast" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const liveRegion = screen.getByRole("region").querySelector("[aria-live]");
      expect(liveRegion).toHaveAttribute("aria-live", "assertive");
    });

    it("uses polite aria-live for low (non-urgent) glucose", () => {
      render(<GlucoseHero value={65} trend="Falling" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const liveRegion = screen.getByRole("region").querySelector("[aria-live]");
      expect(liveRegion).toHaveAttribute("aria-live", "polite");
    });
  });

  describe("Keyboard Navigation", () => {
    it("is keyboard focusable", () => {
      render(<GlucoseHero value={120} trend="Stable" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const region = screen.getByRole("region");
      expect(region).toHaveAttribute("tabIndex", "0");
    });

    it("has visible focus indicator class", () => {
      render(<GlucoseHero value={120} trend="Stable" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const region = screen.getByRole("region");
      expect(region.className).toMatch(/focus-visible:ring/);
    });
  });

  describe("Accessible Pump Status Labels", () => {
    it("provides accessible IoB label", () => {
      render(<GlucoseHero value={120} trend="Stable" iob={2.5} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const metricsGroup = screen.getByRole("group", {
        name: /pump status metrics/i,
      });
      expect(metricsGroup).toBeInTheDocument();

      const iobContainer = metricsGroup.querySelector('[aria-label*="Insulin on board"]');
      expect(iobContainer).toHaveAttribute(
        "aria-label",
        "Insulin on board: 2.50 units"
      );
    });

    it("provides accessible basal rate label", () => {
      render(<GlucoseHero value={120} trend="Stable" iob={null} basalRate={1.5} batteryPct={null} reservoirUnits={null} />);

      const metricsGroup = screen.getByRole("group");
      const basalContainer = metricsGroup.querySelector('[aria-label*="Basal rate"]');
      expect(basalContainer).toHaveAttribute(
        "aria-label",
        "Basal rate: 1.50 units per hour"
      );
    });

    it("provides accessible battery label", () => {
      render(<GlucoseHero value={120} trend="Stable" iob={null} basalRate={null} batteryPct={85} reservoirUnits={null} />);

      const metricsGroup = screen.getByRole("group");
      const batteryContainer = metricsGroup.querySelector('[aria-label*="Battery"]');
      expect(batteryContainer).toHaveAttribute(
        "aria-label",
        "Battery: 85 percent"
      );
    });

    it("indicates unavailable IoB accessibly", () => {
      render(<GlucoseHero value={120} trend="Stable" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} />);

      const metricsGroup = screen.getByRole("group");
      const iobContainer = metricsGroup.querySelector('[aria-label*="Insulin on board"]');
      expect(iobContainer).toHaveAttribute(
        "aria-label",
        "Insulin on board: unavailable"
      );
    });

    it("has screen-reader-only full text for abbreviations", () => {
      render(<GlucoseHero value={120} trend="Stable" iob={2.5} basalRate={1.5} batteryPct={85} reservoirUnits={180} />);

      expect(screen.getAllByText("Insulin on board").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Basal rate").length).toBeGreaterThan(0);
    });
  });

  describe("Loading State Accessibility", () => {
    it("indicates loading state with aria-busy", () => {
      render(<GlucoseHero value={null} trend="Unknown" iob={null} basalRate={null} batteryPct={null} reservoirUnits={null} isLoading />);

      const region = screen.getByRole("region");
      expect(region).toHaveAttribute("aria-busy", "true");
      expect(region).toHaveAttribute("aria-label", "Loading glucose reading");
    });
  });
});

describe("Accessibility Helper Functions", () => {
  describe("buildGlucoseAnnouncement", () => {
    it("builds correct announcement for in-range glucose", () => {
      const result = buildGlucoseAnnouncement(142, "falling slowly", "in-range");
      expect(result).toBe(
        "Glucose 142 milligrams per deciliter, falling slowly, in target range"
      );
    });

    it("builds correct announcement for urgent low", () => {
      const result = buildGlucoseAnnouncement(50, "falling fast", "urgent-low");
      expect(result).toBe(
        "Glucose 50 milligrams per deciliter, falling fast, dangerously low"
      );
    });

    it("returns unavailable message for null value", () => {
      const result = buildGlucoseAnnouncement(null, "unknown", "in-range");
      expect(result).toBe("Glucose reading unavailable");
    });

    it("rounds glucose value", () => {
      const result = buildGlucoseAnnouncement(142.7, "stable", "in-range");
      expect(result).toContain("Glucose 143");
    });

    it("speaks the converted value and British 'litre' for mmol users", () => {
      // value stays mg/dL (180); spoken as the converted 10.0 mmol.
      const result = buildGlucoseAnnouncement(
        180,
        "falling slowly",
        "in-range",
        "mmol"
      );
      expect(result).toBe(
        "Glucose 10.0 millimoles per litre, falling slowly, in target range"
      );
    });
  });

  describe("getRangeStatus", () => {
    it("returns correct status for each range", () => {
      expect(getRangeStatus("inRange")).toBe("in-range");
      expect(getRangeStatus("low")).toBe("low");
      expect(getRangeStatus("high")).toBe("high");
      expect(getRangeStatus("urgentLow")).toBe("urgent-low");
      expect(getRangeStatus("urgentHigh")).toBe("urgent-high");
    });
  });

  describe("isUrgentState", () => {
    it("returns true for urgent states", () => {
      expect(isUrgentState("urgentLow")).toBe(true);
      expect(isUrgentState("urgentHigh")).toBe(true);
    });

    it("returns false for non-urgent states", () => {
      expect(isUrgentState("inRange")).toBe(false);
      expect(isUrgentState("low")).toBe(false);
      expect(isUrgentState("high")).toBe(false);
    });
  });

  describe("classifyGlucose", () => {
    it("classifies glucose ranges correctly", () => {
      expect(classifyGlucose(50)).toBe("urgentLow");
      expect(classifyGlucose(65)).toBe("low");
      expect(classifyGlucose(120)).toBe("inRange");
      expect(classifyGlucose(200)).toBe("high");
      expect(classifyGlucose(280)).toBe("urgentHigh");
      expect(classifyGlucose(null)).toBe("inRange");
    });
  });
});
