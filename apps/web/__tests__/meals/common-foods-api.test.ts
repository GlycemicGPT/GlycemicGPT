/**
 * Tests for the common-foods + save/link API client (api.ts), exercised through
 * a mocked global.fetch (mirrors meal-api.test.ts). Covers list/update/delete,
 * save-as + link, and the owner-scoped 404 / 409 / 422 error contract.
 */

// Force module scope: this file uses in-test `require()` rather than top-level
// imports, so without an export it is a global script and its `jsonResponse`
// collides with the identically-named helper in meal-api.test.ts ("Duplicate
// function implementation" under tsc).
export {};

function jsonResponse(status: number, body: unknown, ok?: boolean) {
  return {
    ok: ok ?? (status >= 200 && status < 300),
    status,
    json: async () => body,
  };
}

beforeEach(() => {
  jest.resetModules();
});

describe("listCommonFoods", () => {
  it("requests limit/offset and returns the wrapper", async () => {
    const payload = {
      common_foods: [{ id: "cf-1", name: "Oatmeal" }],
      total: 1,
    };
    const mockFetch = jest.fn().mockResolvedValue(jsonResponse(200, payload));
    global.fetch = mockFetch;

    const { listCommonFoods } = require("@/lib/api");
    const result = await listCommonFoods(50, 0);

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/common-foods?limit=50&offset=0",
      expect.objectContaining({ credentials: "include" })
    );
    expect(result).toEqual(payload);
  });

  it("throws a MealApiError on a feature-off 404", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(
        jsonResponse(404, { detail: "Meal intelligence is not enabled." })
      );

    const { listCommonFoods, MealApiError } = require("@/lib/api");
    await expect(listCommonFoods()).rejects.toBeInstanceOf(MealApiError);
    await expect(listCommonFoods()).rejects.toMatchObject({ status: 404 });
  });
});

describe("updateCommonFood", () => {
  it("PATCHes the name + carb range and returns the baseline", async () => {
    const updated = { id: "cf-1", name: "Steel-cut oats" };
    const mockFetch = jest.fn().mockResolvedValue(jsonResponse(200, updated));
    global.fetch = mockFetch;

    const { updateCommonFood } = require("@/lib/api");
    const result = await updateCommonFood("cf-1", {
      name: "Steel-cut oats",
      carbs_low: 30,
      carbs_high: 45,
    });

    expect(result).toEqual(updated);
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/common-foods/cf-1");
    expect(options.method).toBe("PATCH");
    expect(JSON.parse(options.body)).toEqual({
      name: "Steel-cut oats",
      carbs_low: 30,
      carbs_high: 45,
    });
    expect(options.credentials).toBe("include");
  });

  it("surfaces a name-in-use 409 as a MealApiError", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      jsonResponse(409, {
        detail: "A common food with that name already exists.",
      })
    );
    const { updateCommonFood, MealApiError } = require("@/lib/api");
    await expect(
      updateCommonFood("cf-1", { name: "Oatmeal" })
    ).rejects.toBeInstanceOf(MealApiError);
    await expect(
      updateCommonFood("cf-1", { name: "Oatmeal" })
    ).rejects.toMatchObject({ status: 409 });
  });

  it("surfaces an out-of-range 422 as a MealApiError", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(
        jsonResponse(422, { detail: "carbs_low must not exceed carbs_high" })
      );
    const { updateCommonFood, MealApiError } = require("@/lib/api");
    await expect(
      updateCommonFood("cf-1", { carbs_low: 50, carbs_high: 10 })
    ).rejects.toBeInstanceOf(MealApiError);
    await expect(
      updateCommonFood("cf-1", { carbs_low: 50, carbs_high: 10 })
    ).rejects.toMatchObject({ status: 422 });
  });

  it("rejects a cross-user id with an owner-scoped 404 (IDOR)", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "Common food not found." }));
    const { updateCommonFood, MealApiError } = require("@/lib/api");
    await expect(
      updateCommonFood("someone-elses-id", { name: "x" })
    ).rejects.toMatchObject({ status: 404 });
    await expect(
      updateCommonFood("someone-elses-id", { name: "x" })
    ).rejects.toBeInstanceOf(MealApiError);
  });
});

describe("deleteCommonFood", () => {
  it("issues a DELETE and resolves on 204", async () => {
    const mockFetch = jest.fn().mockResolvedValue({ ok: true, status: 204 });
    global.fetch = mockFetch;

    const { deleteCommonFood } = require("@/lib/api");
    await expect(deleteCommonFood("cf-1")).resolves.toBeUndefined();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/common-foods/cf-1",
      expect.objectContaining({ method: "DELETE" })
    );
  });

  it("rejects a cross-user id with an owner-scoped 404 (IDOR)", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "Common food not found." }));
    const { deleteCommonFood, MealApiError } = require("@/lib/api");
    await expect(deleteCommonFood("someone-elses-id")).rejects.toBeInstanceOf(
      MealApiError
    );
    await expect(deleteCommonFood("someone-elses-id")).rejects.toMatchObject({
      status: 404,
    });
  });
});

describe("saveRecordAsCommonFood", () => {
  it("POSTs the name and returns the saved baseline", async () => {
    const saved = { id: "cf-9", name: "Oatmeal" };
    const mockFetch = jest.fn().mockResolvedValue(jsonResponse(201, saved));
    global.fetch = mockFetch;

    const { saveRecordAsCommonFood } = require("@/lib/api");
    const result = await saveRecordAsCommonFood("rec-1", "Oatmeal");

    expect(result).toEqual(saved);
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/food-records/rec-1/save-as-common-food");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ name: "Oatmeal" });
    expect(options.credentials).toBe("include");
  });

  it("rejects a cross-user record id with an owner-scoped 404 (IDOR)", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "Food record not found." }));
    const { saveRecordAsCommonFood, MealApiError } = require("@/lib/api");
    await expect(
      saveRecordAsCommonFood("someone-elses-id", "x")
    ).rejects.toBeInstanceOf(MealApiError);
    await expect(
      saveRecordAsCommonFood("someone-elses-id", "x")
    ).rejects.toMatchObject({ status: 404 });
  });
});

describe("linkRecordToCommonFood", () => {
  it("POSTs the common_food_id and returns the refreshed record", async () => {
    const updated = { id: "rec-1", common_food_id: "cf-1" };
    const mockFetch = jest.fn().mockResolvedValue(jsonResponse(200, updated));
    global.fetch = mockFetch;

    const { linkRecordToCommonFood } = require("@/lib/api");
    const result = await linkRecordToCommonFood("rec-1", "cf-1");

    expect(result).toEqual(updated);
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/food-records/rec-1/link-common-food");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ common_food_id: "cf-1" });
    expect(options.credentials).toBe("include");
  });

  it("rejects a cross-user common-food id with an owner-scoped 404 (IDOR)", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "Common food not found." }));
    const { linkRecordToCommonFood, MealApiError } = require("@/lib/api");
    await expect(
      linkRecordToCommonFood("rec-1", "someone-elses-common-food")
    ).rejects.toBeInstanceOf(MealApiError);
    await expect(
      linkRecordToCommonFood("rec-1", "someone-elses-common-food")
    ).rejects.toMatchObject({ status: 404 });
  });
});
