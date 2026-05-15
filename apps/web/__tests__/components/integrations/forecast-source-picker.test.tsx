/**
 * ForecastSourcePicker Tests (Story 43.12 PR 4)
 *
 * Covers the UX rules from the design doc Section 3:
 * - Picker auto-hides when no source has published a forecast.
 * - Renders the dropdown for `auto` + `none` + each available engine.
 * - PUT round-trip refreshes the hook so `effective_source` /
 *   `forecast_unavailable_reason` reflect the new pick.
 * - Status hint dispatches on `forecast_unavailable_reason`.
 */

import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { ForecastSourcePicker } from "@/components/integrations/forecast-source-picker";
import {
  getForecast,
  updateForecastSource,
  type ForecastReadResponse,
} from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getForecast: jest.fn(),
  updateForecastSource: jest.fn(),
}));

const mockGetForecast = getForecast as jest.MockedFunction<typeof getForecast>;
const mockUpdate = updateForecastSource as jest.MockedFunction<
  typeof updateForecastSource
>;

function makeResponse(
  overrides: Partial<ForecastReadResponse> = {}
): ForecastReadResponse {
  return {
    source_preference: "auto",
    effective_source: "loop",
    available_sources: ["loop"],
    forecast: {
      source_engine: "loop",
      source_uploader: "Loop",
      issued_at: "2026-05-15T12:00:00Z",
      start_at: "2026-05-15T12:00:00Z",
      step_minutes: 5,
      horizon_minutes: 180,
      curves_mgdl: { main: [120, 125] },
      default_curve_name: "main",
    },
    forecast_unavailable_reason: null,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("ForecastSourcePicker", () => {
  it("auto-hides when no source has published a forecast", async () => {
    mockGetForecast.mockResolvedValue(
      makeResponse({
        available_sources: [],
        effective_source: null,
        forecast: null,
        forecast_unavailable_reason: "no_sources",
      })
    );

    const { container } = render(<ForecastSourcePicker />);

    await waitFor(() => {
      expect(mockGetForecast).toHaveBeenCalled();
    });

    expect(
      container.querySelector('[data-testid="forecast-source-picker"]')
    ).toBeNull();
  });

  it("renders a dropdown with Auto, None, and each available engine", async () => {
    mockGetForecast.mockResolvedValue(
      makeResponse({ available_sources: ["loop", "aaps"] })
    );

    render(<ForecastSourcePicker />);

    await waitFor(() =>
      expect(
        screen.queryByTestId("forecast-source-picker")
      ).not.toBeNull()
    );

    expect(screen.getByText("Auto (default)")).not.toBeNull();
    expect(screen.getByText("None (don't show)")).not.toBeNull();
    expect(screen.getByText("Loop")).not.toBeNull();
    expect(screen.getByText("AAPS")).not.toBeNull();
  });

  it("PUTs the new preference and re-reads on change", async () => {
    mockGetForecast.mockResolvedValue(
      makeResponse({ available_sources: ["loop", "aaps"] })
    );
    mockUpdate.mockResolvedValue({ source_preference: "aaps" });

    render(<ForecastSourcePicker />);

    await waitFor(() =>
      expect(screen.queryByTestId("forecast-source-picker")).not.toBeNull()
    );

    const select = screen.getByRole("combobox") as HTMLSelectElement;

    await act(async () => {
      fireEvent.change(select, { target: { value: "aaps" } });
    });

    expect(mockUpdate).toHaveBeenCalledWith("aaps");
    // Hook refresh after PUT
    expect(mockGetForecast).toHaveBeenCalledTimes(2);
  });

  it("shows the needs_pick hint when multiple sources require a pick", async () => {
    mockGetForecast.mockResolvedValue(
      makeResponse({
        available_sources: ["loop", "aaps"],
        effective_source: null,
        forecast: null,
        forecast_unavailable_reason: "needs_pick",
      })
    );

    render(<ForecastSourcePicker />);

    await waitFor(() =>
      expect(screen.queryByTestId("forecast-picker-hint")).not.toBeNull()
    );
    expect(
      screen.getByTestId("forecast-picker-hint").textContent
    ).toContain("pick one");
  });

  it("shows the opted_out hint when user picked None", async () => {
    mockGetForecast.mockResolvedValue(
      makeResponse({
        source_preference: "none",
        effective_source: null,
        forecast: null,
        forecast_unavailable_reason: "opted_out",
      })
    );

    render(<ForecastSourcePicker />);

    await waitFor(() =>
      expect(screen.queryByTestId("forecast-picker-hint")).not.toBeNull()
    );
    expect(
      screen.getByTestId("forecast-picker-hint").textContent?.toLowerCase()
    ).toContain("off");
  });

  it("shows the stale hint when forecast data is older than 30 minutes", async () => {
    mockGetForecast.mockResolvedValue(
      makeResponse({
        forecast: null,
        forecast_unavailable_reason: "stale",
      })
    );

    render(<ForecastSourcePicker />);

    await waitFor(() =>
      expect(screen.queryByTestId("forecast-picker-hint")).not.toBeNull()
    );
    expect(
      screen.getByTestId("forecast-picker-hint").textContent?.toLowerCase()
    ).toContain("older than 30 minutes");
  });
});
