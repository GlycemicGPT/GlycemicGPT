import { lttbDownsample, type TimeSeriesPoint } from "@/lib/downsample";

function makePoints(values: number[], startMs = 0, intervalMs = 5000): TimeSeriesPoint[] {
  return values.map((v, i) => ({ timestamp: startMs + i * intervalMs, value: v }));
}

describe("lttbDownsample", () => {
  it("returns original array when target >= data length", () => {
    const data = makePoints([100, 110, 120]);
    expect(lttbDownsample(data, 5)).toBe(data);
    expect(lttbDownsample(data, 3)).toBe(data);
  });

  it("returns original array when target < 2", () => {
    const data = makePoints([100, 110, 120]);
    expect(lttbDownsample(data, 1)).toBe(data);
    expect(lttbDownsample(data, 0)).toBe(data);
    expect(lttbDownsample(data, -1)).toBe(data);
  });

  it("returns empty array as-is", () => {
    const data: TimeSeriesPoint[] = [];
    expect(lttbDownsample(data, 10)).toBe(data);
  });

  it("returns single-point array as-is", () => {
    const data = makePoints([100]);
    expect(lttbDownsample(data, 10)).toBe(data);
  });

  it("returns two-point array as-is", () => {
    const data = makePoints([100, 200]);
    expect(lttbDownsample(data, 10)).toBe(data);
  });

  it("always keeps first and last points", () => {
    const data = makePoints([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]);
    const result = lttbDownsample(data, 3);
    expect(result.length).toBe(3);
    expect(result[0]).toBe(data[0]);
    expect(result[result.length - 1]).toBe(data[data.length - 1]);
  });

  it("downsamples to exact target count", () => {
    const data = makePoints(Array.from({ length: 100 }, (_, i) => 80 + Math.sin(i / 5) * 40));
    const result = lttbDownsample(data, 20);
    expect(result.length).toBe(20);
  });

  it("preserves spikes (large triangle area)", () => {
    // Flat data with a single large spike -- LTTB should keep the spike
    const values = Array.from({ length: 50 }, () => 100);
    values[25] = 400; // big spike
    const data = makePoints(values);
    const result = lttbDownsample(data, 5);
    const spikeKept = result.some((p) => p.value === 400);
    expect(spikeKept).toBe(true);
  });

  it("handles all-identical values without crashing", () => {
    const data = makePoints(Array.from({ length: 20 }, () => 150));
    const result = lttbDownsample(data, 5);
    expect(result.length).toBe(5);
    result.forEach((p) => expect(p.value).toBe(150));
  });

  it("handles all-identical timestamps gracefully", () => {
    const data = Array.from({ length: 10 }, (_, i) => ({
      timestamp: 1000, // all same
      value: 100 + i,
    }));
    const result = lttbDownsample(data, 4);
    expect(result.length).toBe(4);
  });

  it("preserves extra properties on generic type", () => {
    interface Extended extends TimeSeriesPoint {
      color: string;
    }
    const data: Extended[] = [
      { timestamp: 0, value: 100, color: "green" },
      { timestamp: 1, value: 200, color: "red" },
      { timestamp: 2, value: 150, color: "green" },
      { timestamp: 3, value: 300, color: "red" },
      { timestamp: 4, value: 100, color: "green" },
    ];
    const result = lttbDownsample(data, 3);
    expect(result.length).toBe(3);
    // First and last are always kept; verify their colors match original
    expect(result[0].color).toBe("green");
    expect(result[result.length - 1].color).toBe("green");
    result.forEach((p) => expect(["green", "red"]).toContain(p.color));
  });

  it("target = 2 returns only first and last", () => {
    const data = makePoints([10, 50, 300, 20, 90]);
    const result = lttbDownsample(data, 2);
    expect(result.length).toBe(2);
    expect(result[0]).toBe(data[0]);
    expect(result[1]).toBe(data[data.length - 1]);
  });

  it("does not duplicate the last point", () => {
    // Regression: bucketEnd could include data.length-1, causing the
    // last point to appear twice (once from bucket selection, once from
    // the explicit "always keep last" push).
    const data = makePoints([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]);
    const result = lttbDownsample(data, 5);
    expect(result.length).toBe(5);
    // Last point should appear exactly once
    const lastTs = data[data.length - 1].timestamp;
    const count = result.filter((p) => p.timestamp === lastTs).length;
    expect(count).toBe(1);
  });
});
