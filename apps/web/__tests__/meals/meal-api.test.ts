/**
 * Tests for the food-records API client (api.ts), exercised through a mocked
 * global.fetch (mirrors __tests__/api-fetch.test.ts). Covers list/detail/delete,
 * the multipart upload, the meal-intelligence probe, and owner-scoped errors.
 */

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

describe("listFoodRecords", () => {
  it("requests limit/offset and returns the wrapper", async () => {
    const payload = { records: [{ id: "a" }], total: 1 };
    const mockFetch = jest.fn().mockResolvedValue(jsonResponse(200, payload));
    global.fetch = mockFetch;

    const { listFoodRecords } = require("@/lib/api");
    const result = await listFoodRecords(50, 0);

    expect(mockFetch).toHaveBeenCalledWith(
      "/api/food-records?limit=50&offset=0",
      expect.objectContaining({ credentials: "include" })
    );
    expect(result).toEqual(payload);
  });

  it("throws a MealApiError carrying status + detail on a feature-off 404", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(
        jsonResponse(404, { detail: "Meal intelligence is not enabled." })
      );

    const { listFoodRecords, MealApiError } = require("@/lib/api");
    await expect(listFoodRecords()).rejects.toBeInstanceOf(MealApiError);
    await expect(listFoodRecords()).rejects.toMatchObject({
      status: 404,
      detail: "Meal intelligence is not enabled.",
    });
  });
});

describe("getFoodRecord", () => {
  it("fetches a single record by id", async () => {
    const mockFetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(200, { id: "rec-1" }));
    global.fetch = mockFetch;

    const { getFoodRecord } = require("@/lib/api");
    await getFoodRecord("rec-1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/food-records/rec-1",
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("rejects a cross-user / missing record with an owner-scoped 404", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "Food record not found." }));

    const { getFoodRecord, MealApiError } = require("@/lib/api");
    await expect(getFoodRecord("someone-elses-id")).rejects.toMatchObject({
      status: 404,
      detail: "Food record not found.",
    });
    await expect(getFoodRecord("someone-elses-id")).rejects.toBeInstanceOf(
      MealApiError
    );
  });
});

describe("uploadFoodRecord", () => {
  it("POSTs a multipart 'file' part and returns the record", async () => {
    const mockFetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(201, { id: "new-rec" }));
    global.fetch = mockFetch;

    const { uploadFoodRecord } = require("@/lib/api");
    const blob = new Blob(["jpeg-bytes"], { type: "image/jpeg" });
    const result = await uploadFoodRecord(blob);

    expect(result).toEqual({ id: "new-rec" });
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/food-records");
    expect(options.method).toBe("POST");
    expect(options.body).toBeInstanceOf(FormData);
    expect((options.body as FormData).get("file")).toBeInstanceOf(Blob);
    // The browser must set the multipart Content-Type (with boundary) itself.
    const headers = new Headers(options.headers);
    expect(headers.has("Content-Type")).toBe(false);
  });

  it("propagates a vision-unavailable 422 as a MealApiError", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      jsonResponse(422, {
        detail: "Vision is not available on your current AI provider.",
      })
    );
    const { uploadFoodRecord } = require("@/lib/api");
    const blob = new Blob(["x"], { type: "image/jpeg" });
    await expect(uploadFoodRecord(blob)).rejects.toMatchObject({ status: 422 });
  });
});

describe("fetchFoodRecordPhotoObjectUrl", () => {
  it("fetches the photo (credentialed) and returns an object URL", async () => {
    const fakeBlob = new Blob(["bytes"], { type: "image/jpeg" });
    const mockFetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => fakeBlob,
    });
    global.fetch = mockFetch;
    (URL as unknown as { createObjectURL: jest.Mock }).createObjectURL = jest.fn(
      () => "blob:meal-photo"
    );

    const { fetchFoodRecordPhotoObjectUrl } = require("@/lib/api");
    const url = await fetchFoodRecordPhotoObjectUrl("rec-1");

    expect(url).toBe("blob:meal-photo");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/food-records/rec-1/photo",
      expect.objectContaining({ credentials: "include" })
    );
    expect(URL.createObjectURL).toHaveBeenCalledWith(fakeBlob);
  });

  it("throws a MealApiError when the photo is unavailable (404)", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(404, { detail: "Meal photo not available." }));
    const { fetchFoodRecordPhotoObjectUrl, MealApiError } = require("@/lib/api");
    await expect(fetchFoodRecordPhotoObjectUrl("rec-1")).rejects.toBeInstanceOf(
      MealApiError
    );
  });
});

describe("deleteFoodRecord", () => {
  it("issues a DELETE and resolves on 204", async () => {
    const mockFetch = jest
      .fn()
      .mockResolvedValue({ ok: true, status: 204 });
    global.fetch = mockFetch;

    const { deleteFoodRecord } = require("@/lib/api");
    await expect(deleteFoodRecord("rec-1")).resolves.toBeUndefined();
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/food-records/rec-1",
      expect.objectContaining({ method: "DELETE" })
    );
  });
});

describe("getMealIntelligenceStatus", () => {
  it("reports enabled on a successful probe", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(jsonResponse(200, { records: [], total: 0 }));
    const { getMealIntelligenceStatus } = require("@/lib/api");
    expect(await getMealIntelligenceStatus()).toEqual({ enabled: true });
  });

  it("reports disabled only on a 404 whose detail says 'not enabled'", async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue(
        jsonResponse(404, { detail: "Meal intelligence is not enabled." })
      );
    const { getMealIntelligenceStatus } = require("@/lib/api");
    expect(await getMealIntelligenceStatus()).toEqual({ enabled: false });
  });

  it("treats a transient/other failure as available (degraded, never hides the feature)", async () => {
    const { getMealIntelligenceStatus: viaServerError } = (() => {
      global.fetch = jest
        .fn()
        .mockResolvedValue(jsonResponse(500, { detail: "boom" }));
      return require("@/lib/api");
    })();
    expect(await viaServerError()).toEqual({ enabled: true });

    jest.resetModules();
    global.fetch = jest.fn().mockRejectedValue(new Error("network down"));
    const { getMealIntelligenceStatus: viaNetwork } = require("@/lib/api");
    expect(await viaNetwork()).toEqual({ enabled: true });
  });
});
