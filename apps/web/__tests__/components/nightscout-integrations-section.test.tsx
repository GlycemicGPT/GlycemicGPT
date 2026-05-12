/**
 * Tests for NightscoutIntegrationsSection.
 *
 * Specifically validates that soft-deleted (`is_active=false`) connections
 * are hidden from the list. The backend's DELETE endpoint deactivates
 * rather than hard-deleting to preserve attribution on historical
 * pump_events (`source = "nightscout:<id>"`), but the list endpoint
 * still returns those rows -- the UI is responsible for filtering.
 *
 * Regression coverage for: users reported clicking Delete appeared to do
 * nothing because the soft-deleted row immediately re-appeared on refetch.
 */

import { render, screen } from "@testing-library/react";
import { NightscoutIntegrationsSection } from "../../src/components/integrations/nightscout-integrations-section";
import type { NightscoutConnectionResponse } from "../../src/lib/api";

// framer-motion shows up via CollapsibleSection -- mock to avoid jsdom
// animation noise.
jest.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      ...props
    }: {
      children: React.ReactNode;
      [key: string]: unknown;
    }) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

function makeConn(
  overrides: Partial<NightscoutConnectionResponse>
): NightscoutConnectionResponse {
  return {
    id: "00000000-0000-0000-0000-000000000000",
    name: "Test connection",
    base_url: "https://example.org",
    auth_type: "auto",
    api_version: "v1",
    is_active: true,
    has_credential: true,
    sync_interval_minutes: 5,
    initial_sync_window_days: 7,
    last_sync_status: "ok",
    last_synced_at: "2026-05-11T00:00:00Z",
    last_sync_error: null,
    detected_uploaders_json: null,
    last_evaluated_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const noopHandlers = {
  onCreate: jest.fn(),
  onDelete: jest.fn(),
  onTest: jest.fn(),
  onSync: jest.fn(),
  onUpdate: jest.fn(),
};

describe("NightscoutIntegrationsSection -- is_active filter", () => {
  it("renders only active connections in the list", () => {
    render(
      <NightscoutIntegrationsSection
        connections={[
          makeConn({ id: "active-1", name: "Active One" }),
          makeConn({ id: "inactive-1", name: "Soft Deleted", is_active: false }),
          makeConn({ id: "active-2", name: "Active Two" }),
        ]}
        isOffline={false}
        {...noopHandlers}
      />
    );

    // Active rows are present.
    expect(screen.getByText("Active One")).toBeInTheDocument();
    expect(screen.getByText("Active Two")).toBeInTheDocument();

    // Soft-deleted row is gone (this is the regression -- previously it
    // rendered alongside the active ones).
    expect(screen.queryByText("Soft Deleted")).not.toBeInTheDocument();
  });

  it("reports the count of active connections only", () => {
    render(
      <NightscoutIntegrationsSection
        connections={[
          makeConn({ id: "a", name: "Alpha" }),
          makeConn({ id: "b", name: "Beta", is_active: false }),
          makeConn({ id: "c", name: "Gamma", is_active: false }),
        ]}
        isOffline={false}
        {...noopHandlers}
      />
    );

    // "1 connection" (singular) -- because only Alpha is active.
    expect(screen.getByText(/1 connection/)).toBeInTheDocument();
    expect(screen.queryByText(/3 connection/)).not.toBeInTheDocument();
  });

  it("hides the connections list entirely when all connections are inactive", () => {
    render(
      <NightscoutIntegrationsSection
        connections={[
          makeConn({ id: "a", name: "Alpha", is_active: false }),
          makeConn({ id: "b", name: "Beta", is_active: false }),
        ]}
        isOffline={false}
        {...noopHandlers}
      />
    );

    expect(
      screen.queryByTestId("nightscout-connections-list")
    ).not.toBeInTheDocument();
  });
});
