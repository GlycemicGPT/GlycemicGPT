import {
  MGDL_PER_MMOL,
  mgdlToMmol,
  mmolToMgdl,
  formatGlucose,
  formatTrendRate,
  unitLabel,
  spokenUnit,
  toDisplayNumber,
  clampMgdl,
  toStoredMgdl,
} from "@/lib/glucose-units";

describe("glucose-units", () => {
  describe("MGDL_PER_MMOL", () => {
    it("is the single canonical constant 18.0156", () => {
      // Mirrors the backend src/core/units.py MGDL_PER_MMOL. A second value
      // (18.02 / 18.0182) anywhere is a bug; this pins the exact factor.
      expect(MGDL_PER_MMOL).toBe(18.0156);
    });
  });

  describe("cross-surface consistency contract", () => {
    // The shared fixture every surface must agree on: a stored mg/dL value and
    // the exact mmol/L string each client renders for it. Asserted identically
    // here, in the phone (GlucoseFormat.format -> "%.1f"), the watch
    // (GlucoseDisplayUtils.formatGlucose), and the API (format_glucose_value).
    // Each string is round(x / 18.0156, 1) to one decimal; a drift in the factor
    // or the round-LAST rule on any surface breaks its copy of this table. None
    // of the 8 lands on a .x5 mmol tie, so JS toFixed, Java %.1f, and Python
    // round all produce the same string.
    const CROSS_SURFACE_MMOL: Array<[number, string]> = [
      [54, "3.0"],
      [70, "3.9"],
      [99, "5.5"],
      [100, "5.6"],
      [120, "6.7"],
      [180, "10.0"],
      [250, "13.9"],
      [400, "22.2"],
    ];

    it.each(CROSS_SURFACE_MMOL)(
      "renders %d mg/dL as %s mmol/L on every surface",
      (mgdl, expected) => {
        expect(formatGlucose(mgdl, "mmol")).toBe(expected);
      }
    );

    it.each(CROSS_SURFACE_MMOL)(
      "keeps %d mg/dL as the raw integer string in mg/dL mode",
      (mgdl) => {
        // Only the displayed number changes with the unit; the stored value
        // (and its mg/dL rendering) never does.
        expect(formatGlucose(mgdl, "mgdl")).toBe(String(mgdl));
      }
    );
  });

  describe("clinical anchors", () => {
    // 70 / 18.0156 = 3.886 -> 3.9 ; 180 -> 9.99 -> 10.0 ; 120 -> 6.66 -> 6.7
    it("formats 70 mg/dL as 3.9 mmol", () => {
      expect(formatGlucose(70, "mmol")).toBe("3.9");
    });
    it("formats 180 mg/dL as 10.0 mmol", () => {
      expect(formatGlucose(180, "mmol")).toBe("10.0");
    });
    it("formats 120 mg/dL as 6.7 mmol", () => {
      expect(formatGlucose(120, "mmol")).toBe("6.7");
    });
  });

  describe("formatGlucose precision", () => {
    it("rounds mg/dL to an integer string", () => {
      expect(formatGlucose(142.6, "mgdl")).toBe("143");
      expect(formatGlucose(99.2, "mgdl")).toBe("99");
    });
    it("always shows exactly 1 decimal for mmol", () => {
      expect(formatGlucose(100, "mmol")).toBe("5.6"); // 100/18.0156 = 5.55
      expect(formatGlucose(90, "mmol")).toBe("5.0"); // 90/18.0156 = 4.996 -> 5.0
    });
    it("does not mutate the input", () => {
      const v = 123;
      formatGlucose(v, "mmol");
      expect(v).toBe(123);
    });
  });

  describe("round-trip within tolerance", () => {
    it("mmolToMgdl(mgdlToMmol(x)) stays within +/-1 mg/dL", () => {
      for (const x of [20, 55, 70, 100, 120, 180, 250, 400, 500]) {
        expect(Math.abs(mmolToMgdl(mgdlToMmol(x)) - x)).toBeLessThanOrEqual(1);
      }
    });
    it("a saved mmol input round-trips through integer mg/dL within tolerance", () => {
      // 5.5 mmol -> 99 mg/dL -> 5.5 mmol (the expected, acceptable 'snap').
      const storedMgdl = toStoredMgdl(5.5, "mmol");
      expect(storedMgdl).toBe(99); // round(5.5 * 18.0156) = round(99.08) = 99
      expect(formatGlucose(storedMgdl, "mmol")).toBe("5.5");
    });
  });

  describe("formatTrendRate precision", () => {
    it("keeps 1 decimal for mg/dL/min", () => {
      expect(formatTrendRate(3, "mgdl")).toBe("3.0");
      expect(formatTrendRate(-1.5, "mgdl")).toBe("-1.5");
    });
    it("uses 2 decimals for mmol/L/min so arrows stay distinguishable", () => {
      // 3 mg/dL/min / 18.0156 = 0.166 -> 0.17 (1 decimal would collapse to 0.2)
      expect(formatTrendRate(3, "mmol")).toBe("0.17");
      expect(formatTrendRate(1, "mmol")).toBe("0.06");
    });
    it("converts the rate offset-free (a rate has no zero anchor)", () => {
      // A rate divides by 18.0156 with NO offset, unlike a glucose value -- so a
      // negative rate converts just as cleanly as a positive one. Expected
      // strings are computed by hand (1/18.0156=0.0555->"0.06",
      // 3/18.0156=0.1665->"0.17", -1.5/18.0156=-0.0832->"-0.08") so the
      // assertion is grounded in the offset-free result, not the helper itself.
      expect(formatTrendRate(1, "mmol")).toBe("0.06");
      expect(formatTrendRate(3, "mmol")).toBe("0.17");
      expect(formatTrendRate(-1.5, "mmol")).toBe("-0.08");
      // mg/dL keeps one decimal and never converts.
      expect(formatTrendRate(-1.5, "mgdl")).toBe("-1.5");
    });
  });

  describe("safety bounds display + clamp (medical safety)", () => {
    it("displays the 20-500 mg/dL invariant as 1.1-27.8 mmol", () => {
      expect(toDisplayNumber(20, "mmol")).toBe(1.1);
      expect(toDisplayNumber(500, "mmol")).toBe(27.8);
    });
    it("keeps mg/dL bounds as integers", () => {
      expect(toDisplayNumber(20, "mgdl")).toBe(20);
      expect(toDisplayNumber(500, "mgdl")).toBe(500);
    });
    it("clamp pins a boundary unit-rounding overshoot to the canonical bound", () => {
      // Entering the displayed max (27.8 mmol) round-trips to 501; clamp keeps
      // the wire value at the 500 ceiling (no drift, never crosses).
      expect(toStoredMgdl(27.8, "mmol")).toBe(501);
      expect(clampMgdl(toStoredMgdl(27.8, "mmol"), 20, 500)).toBe(500);
      // A stored value exactly at the bound stays put (no silent drift).
      expect(clampMgdl(500, 20, 500)).toBe(500);
      expect(clampMgdl(20, 20, 500)).toBe(20);
      // In-range values are untouched.
      expect(clampMgdl(toStoredMgdl(5.5, "mmol"), 20, 500)).toBe(99);
    });
    it("the displayed bound is enterable: clamp(round-trip) stays in range, and a stored bound value displays as that bound", () => {
      // Every input min/max across the four settings forms.
      const FORM_BOUNDS: Array<{ min: number; max: number }> = [
        { min: 20, max: 499 }, // safety-limits min-glucose field
        { min: 21, max: 500 }, // safety-limits max-glucose field
        { min: 30, max: 70 }, // glucose-range urgent low
        { min: 40, max: 200 }, // glucose-range low target
        { min: 80, max: 400 }, // glucose-range high target
        { min: 200, max: 500 }, // glucose-range urgent high
        { min: 30, max: 80 }, // alerts urgent low
        { min: 40, max: 100 }, // alerts low warning
        { min: 120, max: 300 }, // alerts high warning
        { min: 150, max: 400 }, // alerts urgent high
      ];
      for (const b of FORM_BOUNDS) {
        const dispMin = toDisplayNumber(b.min, "mmol");
        const dispMax = toDisplayNumber(b.max, "mmol");
        // Entering the advertised bound, after clamp, is always WITHIN the
        // canonical range (never rejected, never crosses the bound). mmol's
        // 1-decimal granularity means it may not hit the bound exactly, but it
        // is always a valid in-range value.
        const storedFromMin = clampMgdl(toStoredMgdl(dispMin, "mmol"), b.min, b.max);
        const storedFromMax = clampMgdl(toStoredMgdl(dispMax, "mmol"), b.min, b.max);
        expect(storedFromMin).toBeGreaterThanOrEqual(b.min);
        expect(storedFromMin).toBeLessThanOrEqual(b.max);
        expect(storedFromMax).toBeGreaterThanOrEqual(b.min);
        expect(storedFromMax).toBeLessThanOrEqual(b.max);
        // mg/dL identity.
        expect(toDisplayNumber(b.min, "mgdl")).toBe(b.min);
        expect(toDisplayNumber(b.max, "mgdl")).toBe(b.max);
      }
    });
    it("the safety floor/ceiling are enterable at their displayed value (no false invalid on load)", () => {
      // The regression the visual pass caught: default max_glucose 500 loaded as
      // 27.8 must be accepted, not flagged invalid. Display == bound, clamp pins
      // the overshoot back to exactly the floor/ceiling.
      expect(clampMgdl(toStoredMgdl(toDisplayNumber(500, "mmol"), "mmol"), 20, 500)).toBe(500);
      expect(clampMgdl(toStoredMgdl(toDisplayNumber(20, "mmol"), "mmol"), 20, 500)).toBe(20);
    });
  });

  describe("labels", () => {
    it("unitLabel", () => {
      expect(unitLabel("mgdl")).toBe("mg/dL");
      expect(unitLabel("mmol")).toBe("mmol/L");
    });
    it("spokenUnit uses British 'litre' for mmol", () => {
      expect(spokenUnit("mgdl")).toBe("milligrams per deciliter");
      expect(spokenUnit("mmol")).toBe("millimoles per litre");
    });
  });
});
