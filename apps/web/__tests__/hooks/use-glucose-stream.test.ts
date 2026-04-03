/**
 * useGlucoseStream Hook Tests
 *
 * Story 4.5: Real-Time Updates via SSE
 */

import { renderHook, act } from "@testing-library/react";

import {
  useGlucoseStream,
  mapBackendTrendToFrontend,
  type BackendTrendDirection,
  type FrontendTrendDirection,
} from "@/hooks/use-glucose-stream";

// Mock EventSource
class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  withCredentials: boolean;
  readyState: number = 0;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  private eventListeners: Map<string, ((event: MessageEvent) => void)[]> = new Map();

  constructor(url: string, options?: { withCredentials?: boolean }) {
    this.url = url;
    this.withCredentials = options?.withCredentials ?? false;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    if (!this.eventListeners.has(type)) {
      this.eventListeners.set(type, []);
    }
    this.eventListeners.get(type)!.push(listener);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void) {
    const listeners = this.eventListeners.get(type);
    if (listeners) {
      const index = listeners.indexOf(listener);
      if (index > -1) {
        listeners.splice(index, 1);
      }
    }
  }

  close() {
    this.readyState = 2;
  }

  // Helper methods for testing
  simulateOpen() {
    this.readyState = 1;
    if (this.onopen) {
      this.onopen(new Event("open"));
    }
  }

  simulateError() {
    if (this.onerror) {
      this.onerror(new Event("error"));
    }
  }

  simulateMessage(type: string, data: unknown) {
    const event = new MessageEvent(type, {
      data: JSON.stringify(data),
    });

    // Call specific event listeners
    const listeners = this.eventListeners.get(type);
    if (listeners) {
      listeners.forEach((listener) => listener(event));
    }
  }

  static clear() {
    MockEventSource.instances = [];
  }

  static getLastInstance(): MockEventSource | undefined {
    return MockEventSource.instances[MockEventSource.instances.length - 1];
  }
}

// Install mock
(global as unknown as { EventSource: typeof MockEventSource }).EventSource = MockEventSource;

describe("mapBackendTrendToFrontend", () => {
  const testCases: [BackendTrendDirection, FrontendTrendDirection][] = [
    ["double_up", "RisingFast"],
    ["single_up", "Rising"],
    ["forty_five_up", "Rising"],
    ["flat", "Stable"],
    ["forty_five_down", "Falling"],
    ["single_down", "Falling"],
    ["double_down", "FallingFast"],
    ["not_computable", "Unknown"],
    ["rate_out_of_range", "Unknown"],
    ["Unknown", "Unknown"],
  ];

  it.each(testCases)("maps %s to %s", (backend, expected) => {
    expect(mapBackendTrendToFrontend(backend)).toBe(expected);
  });

  it("returns Unknown for invalid trends", () => {
    expect(mapBackendTrendToFrontend("InvalidTrend")).toBe("Unknown");
  });
});

describe("useGlucoseStream", () => {
  beforeEach(() => {
    MockEventSource.clear();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
    MockEventSource.clear();
  });

  describe("Initial State", () => {
    it("should start with connecting state when enabled", () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      expect(result.current.connectionState).toBe("connecting");
      expect(result.current.data).toBeNull();
      expect(result.current.error).toBeNull();
      expect(result.current.isConnected).toBe(false);
      expect(result.current.isReconnecting).toBe(false);
    });

    it("should start with closed state when disabled", () => {
      const { result } = renderHook(() => useGlucoseStream(false));

      expect(result.current.connectionState).toBe("closed");
      expect(MockEventSource.instances).toHaveLength(0);
    });
  });

  describe("EventSource Creation", () => {
    it("should create EventSource with correct URL", () => {
      renderHook(() => useGlucoseStream(true));

      expect(MockEventSource.instances).toHaveLength(1);
      expect(MockEventSource.getLastInstance()?.url).toBe(
        "/api/v1/glucose/stream"
      );
    });

    it("should use same-origin request (no withCredentials needed)", () => {
      renderHook(() => useGlucoseStream(true));

      expect(MockEventSource.getLastInstance()?.withCredentials).toBe(false);
    });
  });

  describe("Connection Events", () => {
    it("should update to connected state on open", async () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      act(() => {
        MockEventSource.getLastInstance()?.simulateOpen();
      });

      expect(result.current.connectionState).toBe("connected");
      expect(result.current.isConnected).toBe(true);
    });

    it("should update to reconnecting state on error", async () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      act(() => {
        MockEventSource.getLastInstance()?.simulateOpen();
      });

      act(() => {
        MockEventSource.getLastInstance()?.simulateError();
      });

      expect(result.current.connectionState).toBe("reconnecting");
      expect(result.current.isReconnecting).toBe(true);
    });
  });

  describe("Glucose Events", () => {
    const mockRawGlucoseData = {
      value: 142,
      trend: "flat" as BackendTrendDirection,
      trend_rate: 0.5,
      reading_timestamp: "2024-01-01T12:00:00Z",
      minutes_ago: 2,
      is_stale: false,
      iob: { current: 2.4, is_stale: false },
      timestamp: "2024-01-01T12:00:00Z",
    };

    it("should update data on glucose event with mapped trend", async () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      act(() => {
        MockEventSource.getLastInstance()?.simulateOpen();
      });

      act(() => {
        MockEventSource.getLastInstance()?.simulateMessage("glucose", mockRawGlucoseData);
      });

      expect(result.current.data).not.toBeNull();
      expect(result.current.data?.value).toBe(142);
      // Trend should be mapped from "flat" to "Stable"
      expect(result.current.data?.trend).toBe("Stable");
      expect(result.current.data?.rawTrend).toBe("flat");
      expect(result.current.lastUpdated).toBeInstanceOf(Date);
    });

    it("should update connection state to connected on glucose event", async () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      act(() => {
        MockEventSource.getLastInstance()?.simulateMessage("glucose", mockRawGlucoseData);
      });

      expect(result.current.connectionState).toBe("connected");
    });

  });

  describe("Heartbeat Events", () => {
    it("should maintain connected state on heartbeat", async () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      act(() => {
        MockEventSource.getLastInstance()?.simulateOpen();
      });

      act(() => {
        MockEventSource.getLastInstance()?.simulateMessage("heartbeat", {
          timestamp: new Date().toISOString(),
        });
      });

      expect(result.current.connectionState).toBe("connected");
    });
  });

  describe("Reconnection Logic", () => {
    it("should attempt to reconnect after error", async () => {
      renderHook(() => useGlucoseStream(true));

      const firstInstance = MockEventSource.getLastInstance();

      act(() => {
        firstInstance?.simulateError();
      });

      // Fast-forward past initial reconnect delay (1000ms)
      act(() => {
        jest.advanceTimersByTime(1000);
      });

      // Should have created a new EventSource
      expect(MockEventSource.instances).toHaveLength(2);
    });

    it("should use exponential backoff for reconnection delays", async () => {
      renderHook(() => useGlucoseStream(true));

      // First error - should reconnect after 1s
      act(() => {
        MockEventSource.getLastInstance()?.simulateError();
      });

      act(() => {
        jest.advanceTimersByTime(1000);
      });
      expect(MockEventSource.instances).toHaveLength(2);

      // Second error - should reconnect after 2s
      act(() => {
        MockEventSource.getLastInstance()?.simulateError();
      });

      act(() => {
        jest.advanceTimersByTime(2000);
      });
      expect(MockEventSource.instances).toHaveLength(3);

      // Third error - should reconnect after 4s
      act(() => {
        MockEventSource.getLastInstance()?.simulateError();
      });

      act(() => {
        jest.advanceTimersByTime(4000);
      });
      expect(MockEventSource.instances).toHaveLength(4);
    });

    it("should reset reconnect attempts on successful connection", async () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      // Simulate error and reconnect
      act(() => {
        MockEventSource.getLastInstance()?.simulateError();
      });
      act(() => {
        jest.advanceTimersByTime(1000);
      });

      // Simulate successful connection
      act(() => {
        MockEventSource.getLastInstance()?.simulateOpen();
      });

      expect(result.current.connectionState).toBe("connected");

      // Simulate another error - should use initial delay again
      act(() => {
        MockEventSource.getLastInstance()?.simulateError();
      });
      act(() => {
        jest.advanceTimersByTime(1000);
      });

      expect(MockEventSource.instances).toHaveLength(3);
    });

    it("should give up after max attempts", async () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      // Simulate 10 errors (max attempts) with proper timing
      // Each error triggers a reconnect with exponential backoff
      const delays = [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000, 30000, 30000];

      for (let i = 0; i < 10; i++) {
        act(() => {
          MockEventSource.getLastInstance()?.simulateError();
        });

        // Advance by the correct delay for this attempt
        act(() => {
          jest.advanceTimersByTime(delays[i]);
        });
      }

      // Simulate the 11th error - this should trigger error state since we've exceeded max attempts
      act(() => {
        MockEventSource.getLastInstance()?.simulateError();
      });

      // Should be in error state after max attempts exceeded
      expect(result.current.connectionState).toBe("error");
      expect(result.current.error).not.toBeNull();
    });
  });

  describe("Manual Controls", () => {
    it("should reconnect when reconnect() is called", async () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      const initialInstanceCount = MockEventSource.instances.length;

      act(() => {
        result.current.reconnect();
      });

      expect(MockEventSource.instances).toHaveLength(initialInstanceCount + 1);
    });

    it("should disconnect when disconnect() is called", async () => {
      const { result } = renderHook(() => useGlucoseStream(true));

      act(() => {
        MockEventSource.getLastInstance()?.simulateOpen();
      });

      act(() => {
        result.current.disconnect();
      });

      expect(result.current.connectionState).toBe("closed");
      expect(MockEventSource.getLastInstance()?.readyState).toBe(2); // CLOSED
    });
  });

  describe("Cleanup", () => {
    it("should close EventSource on unmount", () => {
      const { unmount } = renderHook(() => useGlucoseStream(true));

      const instance = MockEventSource.getLastInstance();

      unmount();

      expect(instance?.readyState).toBe(2); // CLOSED
    });

    it("should close EventSource when disabled", () => {
      const { rerender } = renderHook(
        ({ enabled }) => useGlucoseStream(enabled),
        { initialProps: { enabled: true } }
      );

      const instance = MockEventSource.getLastInstance();

      rerender({ enabled: false });

      expect(instance?.readyState).toBe(2); // CLOSED
    });
  });
});
