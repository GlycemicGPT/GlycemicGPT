/**
 * Tests for DataSourcesFreshnessCard.
 *
 * Story 43.5 phase 3: per-source freshness widget on the dashboard.
 * The component is a pure projection of the parent's data into rows
 * + status pills + relative timestamps -- no fetches of its own,
 * no internal timers -- so the tests just feed props.
 */

import { render, screen } from "@testing-library/react";
import { DataSourcesFreshnessCard } from "../../../src/components/dashboard/data-sources-freshness-card";
import type {
  IntegrationResponse,
  NightscoutConnectionResponse,
  NightscoutSyncStatus,
} from "../../../src/lib/api";

const NOW_MS = new Date("2026-05-08T12:00:00.000Z").getTime();

function nsConn(overrides: Partial<NightscoutConnectionResponse> = {}): NightscoutConnectionResponse {
  return {
    id: "ns-1",
    name: "Test NS",
    base_url: "https://example.com",
    auth_type: "secret",
    api_version: "v1",
    is_active: true,
    has_credential: true,
    sync_interval_minutes: 5,
    initial_sync_window_days: 7,
    last_sync_status: "ok" as NightscoutSyncStatus,
    last_synced_at: new Date(NOW_MS - 60_000).toISOString(), // 1 min ago
    last_sync_error: null,
    detected_uploaders_json: null,
    last_evaluated_at: null,
    created_at: "2026-05-01T00:00:00.000Z",
    updated_at: "2026-05-01T00:00:00.000Z",
    ...overrides,
  };
}

function dexcomIntegration(
  overrides: Partial<IntegrationResponse> = {}
): IntegrationResponse {
  return {
    id: "int-dex",
    integration_type: "dexcom",
    status: "connected",
    last_sync_at: new Date(NOW_MS - 5 * 60_000).toISOString(), // 5m ago
    last_error: null,
    has_credentials: true,
    created_at: "2026-05-01T00:00:00.000Z",
    updated_at: "2026-05-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("DataSourcesFreshnessCard", () => {
  it("returns null when no sources are configured", () => {
    const { container } = render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[]}
        dexcom={null}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a single NS connection inside its 2x interval as Connected (green)", () => {
    render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[
          nsConn({
            sync_interval_minutes: 5,
            last_synced_at: new Date(NOW_MS - 3 * 60_000).toISOString(),
          }),
        ]}
        dexcom={null}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Test NS")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("3m ago")).toBeInTheDocument();
  });

  it("renders Lagging (amber) between 2x and 5x interval", () => {
    render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[
          nsConn({
            sync_interval_minutes: 5,
            last_synced_at: new Date(NOW_MS - 15 * 60_000).toISOString(), // 15m ago, 3x interval
          }),
        ]}
        dexcom={null}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Lagging")).toBeInTheDocument();
  });

  it("renders Stale (red) past 5x interval", () => {
    render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[
          nsConn({
            sync_interval_minutes: 5,
            last_synced_at: new Date(NOW_MS - 35 * 60_000).toISOString(), // 35m ago, 7x
          }),
        ]}
        dexcom={null}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Stale")).toBeInTheDocument();
  });

  it("renders Pending when last_sync_status is 'never'", () => {
    render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[
          nsConn({
            last_sync_status: "never",
            last_synced_at: null,
          }),
        ]}
        dexcom={null}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("never")).toBeInTheDocument();
  });

  it("auth_failed forces Stale regardless of last_synced_at recency", () => {
    render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[
          nsConn({
            last_sync_status: "auth_failed",
            // Synced 30 seconds ago — would be "fresh" by recency, but
            // auth_failed means the connection is broken.
            last_synced_at: new Date(NOW_MS - 30_000).toISOString(),
          }),
        ]}
        dexcom={null}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Stale")).toBeInTheDocument();
  });

  it("rate_limited and network statuses force Lagging", () => {
    const { rerender } = render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[
          nsConn({ last_sync_status: "rate_limited" }),
        ]}
        dexcom={null}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Lagging")).toBeInTheDocument();

    rerender(
      <DataSourcesFreshnessCard
        nightscoutConnections={[
          nsConn({ last_sync_status: "network" }),
        ]}
        dexcom={null}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Lagging")).toBeInTheDocument();
  });

  it("excludes inactive (soft-deleted) NS connections from the list", () => {
    render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[
          nsConn({ name: "Active NS", is_active: true }),
          nsConn({
            id: "ns-2",
            name: "Deleted NS",
            is_active: false,
          }),
        ]}
        dexcom={null}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Active NS")).toBeInTheDocument();
    expect(screen.queryByText("Deleted NS")).not.toBeInTheDocument();
  });

  it("renders multi-source mixed states (Dexcom fresh + NS stale)", () => {
    render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[
          nsConn({
            sync_interval_minutes: 5,
            last_synced_at: new Date(NOW_MS - 35 * 60_000).toISOString(), // 7x → Stale
          }),
        ]}
        dexcom={dexcomIntegration({
          last_sync_at: new Date(NOW_MS - 5 * 60_000).toISOString(), // 5m, well under 15m threshold
        })}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Dexcom")).toBeInTheDocument();
    expect(screen.getByText("Test NS")).toBeInTheDocument();
    // Both pills present, in different bands.
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Stale")).toBeInTheDocument();
  });

  it("Dexcom integration: 15m threshold → Lagging, 60m threshold → Stale", () => {
    const { rerender } = render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[]}
        dexcom={dexcomIntegration({
          last_sync_at: new Date(NOW_MS - 20 * 60_000).toISOString(),
        })}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Lagging")).toBeInTheDocument();

    rerender(
      <DataSourcesFreshnessCard
        nightscoutConnections={[]}
        dexcom={dexcomIntegration({
          last_sync_at: new Date(NOW_MS - 90 * 60_000).toISOString(),
        })}
        tandem={null}
        now={NOW_MS}
      />
    );
    expect(screen.getByText("Stale")).toBeInTheDocument();
  });

  it("disconnected direct integration is hidden", () => {
    render(
      <DataSourcesFreshnessCard
        nightscoutConnections={[]}
        dexcom={dexcomIntegration({ status: "disconnected" })}
        tandem={null}
        now={NOW_MS}
      />
    );
    // No Dexcom row -> no sources -> null render.
    expect(screen.queryByText("Dexcom")).not.toBeInTheDocument();
  });
});
