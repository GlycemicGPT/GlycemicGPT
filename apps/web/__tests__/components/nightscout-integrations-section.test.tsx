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

describe("NightscoutIntegrationsSection -- re-import button (43.7d)", () => {
  it("renders a re-import link on every active connection", () => {
    render(
      <NightscoutIntegrationsSection
        connections={[
          makeConn({ id: "c1", name: "Primary" }),
          makeConn({ id: "c2", name: "Spouse" }),
        ]}
        isOffline={false}
        {...noopHandlers}
      />
    );

    const link1 = screen.getByTestId("nightscout-reimport-c1");
    const link2 = screen.getByTestId("nightscout-reimport-c2");
    expect(link1).toHaveAttribute(
      "href",
      "/dashboard/settings/integrations/nightscout/connect?connection=c1"
    );
    expect(link2).toHaveAttribute(
      "href",
      "/dashboard/settings/integrations/nightscout/connect?connection=c2"
    );
  });

  it("URL-encodes the connection id in the re-import href", () => {
    // Real ids are UUIDs (no special chars), but the encoder
    // belt-and-suspenders against odd ids leaking in from future flows.
    render(
      <NightscoutIntegrationsSection
        connections={[makeConn({ id: "id with spaces", name: "Weird" })]}
        isOffline={false}
        {...noopHandlers}
      />
    );
    const link = screen.getByTestId("nightscout-reimport-id with spaces");
    expect(link.getAttribute("href")).toContain(
      "connection=id%20with%20spaces"
    );
  });

  it("disables the re-import link when offline -- pulls out of tab order and blocks keyboard activation", () => {
    render(
      <NightscoutIntegrationsSection
        connections={[makeConn({ id: "c1", name: "Primary" })]}
        isOffline={true}
        {...noopHandlers}
      />
    );

    const link = screen.getByTestId("nightscout-reimport-c1");
    expect(link).toHaveAttribute("aria-disabled", "true");
    // `aria-disabled` alone is advisory -- Tab + Enter would still
    // navigate. tabIndex=-1 removes the link from keyboard tab order.
    expect(link).toHaveAttribute("tabindex", "-1");

    // Pressing Enter must not trigger navigation. We assert by spying
    // on the keydown event and confirming defaultPrevented flips
    // to true via our onKeyDown handler.
    const keyEvent = new KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
      cancelable: true,
    });
    link.dispatchEvent(keyEvent);
    expect(keyEvent.defaultPrevented).toBe(true);

    // Same for Space.
    const spaceEvent = new KeyboardEvent("keydown", {
      key: " ",
      bubbles: true,
      cancelable: true,
    });
    link.dispatchEvent(spaceEvent);
    expect(spaceEvent.defaultPrevented).toBe(true);

    // And a click is still blocked (the mouse path).
    const clickEvent = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
    });
    link.dispatchEvent(clickEvent);
    expect(clickEvent.defaultPrevented).toBe(true);
  });

  it("keeps the re-import link tab-able and interactive when online", () => {
    render(
      <NightscoutIntegrationsSection
        connections={[makeConn({ id: "c1", name: "Primary" })]}
        isOffline={false}
        {...noopHandlers}
      />
    );

    const link = screen.getByTestId("nightscout-reimport-c1");
    expect(link).toHaveAttribute("aria-disabled", "false");
    // No explicit tabIndex when enabled -- inherits anchor's default (0).
    expect(link.getAttribute("tabindex")).toBeNull();

    // Enter does NOT get preventDefault'd in the enabled state.
    const keyEvent = new KeyboardEvent("keydown", {
      key: "Enter",
      bubbles: true,
      cancelable: true,
    });
    link.dispatchEvent(keyEvent);
    expect(keyEvent.defaultPrevented).toBe(false);
  });
});
