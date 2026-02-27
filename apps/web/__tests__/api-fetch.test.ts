/**
 * Story 15.4: apiFetch wrapper tests
 *
 * Tests the global 401 handling in the apiFetch wrapper.
 */

// Save original window.location
const originalLocation = window.location;

beforeEach(() => {
  jest.restoreAllMocks();
  jest.resetModules();
  // Mock window.location.href as writable
  Object.defineProperty(window, "location", {
    writable: true,
    value: { ...originalLocation, href: "http://localhost:3000/dashboard" },
  });
});

afterAll(() => {
  Object.defineProperty(window, "location", {
    writable: true,
    value: originalLocation,
  });
});

describe("apiFetch", () => {
  it("passes credentials: include by default", async () => {
    const mockFetch = jest.fn().mockResolvedValue({
      status: 200,
      ok: true,
    });
    global.fetch = mockFetch;

    const { apiFetch } = require("@/lib/api");
    await apiFetch("http://localhost:8000/api/settings/alert-thresholds");

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/settings/alert-thresholds",
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("redirects to /login?expired=true on 401 from non-auth endpoint", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 401, ok: false });

    const { apiFetch } = require("@/lib/api");
    // apiFetch returns a never-resolving promise on 401 redirect,
    // so we race it with a short timeout
    const result = await Promise.race([
      apiFetch("http://localhost:8000/api/settings/alert-thresholds"),
      new Promise((resolve) => setTimeout(() => resolve("pending"), 50)),
    ]);

    expect(window.location.href).toBe("/login?expired=true");
    expect(result).toBe("pending");
  });

  it("does NOT redirect on 401 from /api/auth/me", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 401, ok: false });

    const { apiFetch } = require("@/lib/api");
    const response = await apiFetch("http://localhost:8000/api/auth/me");

    expect(window.location.href).toBe("http://localhost:3000/dashboard");
    expect(response.status).toBe(401);
  });

  it("does NOT redirect on 401 from /api/auth/login", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 401, ok: false });

    const { apiFetch } = require("@/lib/api");
    const response = await apiFetch("http://localhost:8000/api/auth/login");

    expect(window.location.href).toBe("http://localhost:3000/dashboard");
    expect(response.status).toBe(401);
  });

  it("does NOT redirect on 401 from /api/auth/register", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 401, ok: false });

    const { apiFetch } = require("@/lib/api");
    const response = await apiFetch("http://localhost:8000/api/auth/register");

    expect(window.location.href).toBe("http://localhost:3000/dashboard");
    expect(response.status).toBe(401);
  });

  it("does NOT redirect on 401 from /api/auth/logout", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 401, ok: false });

    const { apiFetch } = require("@/lib/api");
    const response = await apiFetch("http://localhost:8000/api/auth/logout");

    expect(window.location.href).toBe("http://localhost:3000/dashboard");
    expect(response.status).toBe(401);
  });

  it("does NOT redirect on non-401 errors", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 500, ok: false });

    const { apiFetch } = require("@/lib/api");
    const response = await apiFetch(
      "http://localhost:8000/api/settings/alert-thresholds"
    );

    expect(window.location.href).toBe("http://localhost:3000/dashboard");
    expect(response.status).toBe(500);
  });

  it("returns the response object for normal responses", async () => {
    const mockResponse = { status: 200, ok: true, json: jest.fn() };
    global.fetch = jest.fn().mockResolvedValue(mockResponse);

    const { apiFetch } = require("@/lib/api");
    const result = await apiFetch("http://localhost:8000/api/alerts/active");

    expect(result).toBe(mockResponse);
  });

  it("merges custom options with credentials", async () => {
    const mockFetch = jest.fn().mockResolvedValue({ status: 200, ok: true });
    global.fetch = mockFetch;

    const { apiFetch } = require("@/lib/api");
    await apiFetch("http://localhost:8000/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "test" }),
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/ai/chat",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ message: "test" }),
      })
    );
    // Headers are converted to a Headers instance by apiFetch (Story 28.4 CSRF support)
    const actualHeaders = mockFetch.mock.calls[0][1].headers;
    expect(actualHeaders).toBeInstanceOf(Headers);
    expect(actualHeaders.get("Content-Type")).toBe("application/json");
  });

  it("uses exact pathname match (not substring) for auth endpoint exclusion", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 401, ok: false });

    const { apiFetch } = require("@/lib/api");
    // /api/auth/me-sessions contains /api/auth/me as substring but should NOT be excluded
    const result = await Promise.race([
      apiFetch("http://localhost:8000/api/auth/me-sessions"),
      new Promise((resolve) => setTimeout(() => resolve("pending"), 50)),
    ]);

    expect(window.location.href).toBe("/login?expired=true");
    expect(result).toBe("pending");
  });
});

describe("apiFetch integration - 401 through higher-level function", () => {
  it("getAlertThresholds triggers redirect on 401", async () => {
    global.fetch = jest.fn().mockResolvedValue({ status: 401, ok: false });

    const { getAlertThresholds } = require("@/lib/api");
    // The function should never resolve (apiFetch returns never-resolving promise)
    const result = await Promise.race([
      getAlertThresholds().catch(() => "caught"),
      new Promise((resolve) => setTimeout(() => resolve("pending"), 50)),
    ]);

    expect(window.location.href).toBe("/login?expired=true");
    expect(result).toBe("pending");
  });
});
