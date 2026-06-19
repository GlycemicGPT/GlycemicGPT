/**
 * Tests for the Common foods management page: lists baselines (most-recently-
 * updated-first), the never-dose baseline note, inline rename + re-baseline with
 * 409/422 handled gracefully, the delete-confirm flow (linked records unlink, not
 * deleted), the feature-off dead end (no raw 404), and the empty state.
 * Behavioural assertions only.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("next/link", () => {
  const Link = ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  );
  Link.displayName = "Link";
  return Link;
});

const mockList = jest.fn();
const mockUpdate = jest.fn();
const mockDelete = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  ...jest.requireActual("@/lib/api"),
  listCommonFoods: (...args: unknown[]) => mockList(...args),
  updateCommonFood: (...args: unknown[]) => mockUpdate(...args),
  deleteCommonFood: (...args: unknown[]) => mockDelete(...args),
}));

import CommonFoodsPage from "../../src/app/dashboard/meals/common-foods/page";
import { MealApiError, type CommonFood } from "@/lib/api";

function makeFood(overrides: Partial<CommonFood> = {}): CommonFood {
  return {
    id: "cf-1",
    name: "Oatmeal",
    carbs_low: 40,
    carbs_high: 55,
    nutrition_json: null,
    created_at: "2026-06-19T12:00:00Z",
    updated_at: "2026-06-19T12:00:00Z",
    ...overrides,
  };
}

describe("Common foods page", () => {
  beforeEach(() => {
    mockList.mockReset();
    mockUpdate.mockReset();
    mockDelete.mockReset();
  });

  it("lists baselines in the server order (most recently updated first)", async () => {
    mockList.mockResolvedValue({
      common_foods: [
        makeFood({ id: "cf-1", name: "Greek yogurt" }),
        makeFood({ id: "cf-2", name: "Oatmeal" }),
      ],
      total: 2,
    });
    render(<CommonFoodsPage />);

    const names = await screen.findAllByTestId("common-food-name");
    expect(names.map((n) => n.textContent)).toEqual(["Greek yogurt", "Oatmeal"]);
    expect(mockList).toHaveBeenCalledWith(50, 0);
  });

  it("renders the never-dose baseline note", async () => {
    mockList.mockResolvedValue({ common_foods: [makeFood()], total: 1 });
    render(<CommonFoodsPage />);

    const note = await screen.findByTestId("meal-safety-qualifier");
    expect(note).toHaveTextContent(/not a dose target/i);
    expect(note).toHaveTextContent(/never dose/i);
  });

  it("renders the empty state when there are no baselines", async () => {
    mockList.mockResolvedValue({ common_foods: [], total: 0 });
    render(<CommonFoodsPage />);

    expect(await screen.findByTestId("common-food-empty")).toBeInTheDocument();
  });

  it("renames + re-baselines a common food via PATCH", async () => {
    mockList.mockResolvedValue({ common_foods: [makeFood()], total: 1 });
    mockUpdate.mockResolvedValue(
      makeFood({ name: "Steel-cut oats", carbs_low: 30, carbs_high: 45 })
    );
    render(<CommonFoodsPage />);

    fireEvent.click(await screen.findByTestId("common-food-edit"));
    fireEvent.change(screen.getByTestId("common-food-edit-name"), {
      target: { value: "Steel-cut oats" },
    });
    fireEvent.change(screen.getByTestId("common-food-edit-low"), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByTestId("common-food-edit-high"), {
      target: { value: "45" },
    });
    fireEvent.click(screen.getByTestId("common-food-edit-save"));

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith("cf-1", {
        name: "Steel-cut oats",
        carbs_low: 30,
        carbs_high: 45,
      })
    );
  });

  it("handles a 409 name collision gracefully (inline error, no crash)", async () => {
    mockList.mockResolvedValue({ common_foods: [makeFood()], total: 1 });
    mockUpdate.mockRejectedValue(
      new MealApiError(409, "A common food with that name already exists.")
    );
    render(<CommonFoodsPage />);

    fireEvent.click(await screen.findByTestId("common-food-edit"));
    fireEvent.change(screen.getByTestId("common-food-edit-name"), {
      target: { value: "Greek yogurt" },
    });
    fireEvent.click(screen.getByTestId("common-food-edit-save"));

    expect(await screen.findByTestId("common-food-edit-error")).toHaveTextContent(
      /already have a common food with that name/i
    );
  });

  it("handles a 422 out-of-range from the server gracefully", async () => {
    mockList.mockResolvedValue({ common_foods: [makeFood()], total: 1 });
    mockUpdate.mockRejectedValue(
      new MealApiError(422, "carbohydrate bound above 1000 g")
    );
    render(<CommonFoodsPage />);

    fireEvent.click(await screen.findByTestId("common-food-edit"));
    // A valid client-side range so the request reaches the server (which rejects).
    fireEvent.change(screen.getByTestId("common-food-edit-low"), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByTestId("common-food-edit-high"), {
      target: { value: "40" },
    });
    fireEvent.click(screen.getByTestId("common-food-edit-save"));

    expect(await screen.findByTestId("common-food-edit-error")).toHaveTextContent(
      /between 0 and 1000/i
    );
  });

  it("rejects an inverted range client-side without any network call", async () => {
    mockList.mockResolvedValue({ common_foods: [makeFood()], total: 1 });
    render(<CommonFoodsPage />);

    fireEvent.click(await screen.findByTestId("common-food-edit"));
    fireEvent.change(screen.getByTestId("common-food-edit-low"), {
      target: { value: "50" },
    });
    fireEvent.change(screen.getByTestId("common-food-edit-high"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByTestId("common-food-edit-save"));

    expect(await screen.findByTestId("common-food-edit-error")).toHaveTextContent(
      /low value must not exceed/i
    );
    expect(mockUpdate).not.toHaveBeenCalled();
  });

  it("deletes after confirmation, telling the user linked meals are unlinked, not deleted", async () => {
    mockList.mockResolvedValue({ common_foods: [makeFood()], total: 1 });
    mockDelete.mockResolvedValue(undefined);
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);

    render(<CommonFoodsPage />);
    fireEvent.click(await screen.findByTestId("common-food-delete"));

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("cf-1"));
    // The confirm copy must not imply the linked meals themselves are deleted.
    const prompt = confirmSpy.mock.calls[0][0] as string;
    expect(prompt).toMatch(/unlinked/i);
    expect(prompt).toMatch(/stay logged/i);
    confirmSpy.mockRestore();
  });

  it("does not delete when the confirmation is cancelled", async () => {
    mockList.mockResolvedValue({ common_foods: [makeFood()], total: 1 });
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);

    render(<CommonFoodsPage />);
    fireEvent.click(await screen.findByTestId("common-food-delete"));

    expect(mockDelete).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("paginates: Next requests the next offset and reflects the page count", async () => {
    const pageOne = Array.from({ length: 50 }, (_, i) =>
      makeFood({ id: `cf-${i}`, name: `Food ${i}` })
    );
    const pageTwo = [makeFood({ id: "cf-50", name: "Food 50" })];
    mockList.mockImplementation((_limit: number, offset: number) =>
      Promise.resolve({
        common_foods: offset === 0 ? pageOne : pageTwo,
        total: 51,
      })
    );
    render(<CommonFoodsPage />);

    // Page 1 fully loaded, two pages total (51 rows / 50 per page).
    await waitFor(() =>
      expect(screen.getAllByTestId("common-food-row")).toHaveLength(50)
    );
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(mockList).toHaveBeenCalledWith(50, 50));
    expect(await screen.findByText("Page 2 of 2")).toBeInTheDocument();
  });

  it("steps back a page when the last row on a non-first page is deleted", async () => {
    const pageOne = Array.from({ length: 50 }, (_, i) =>
      makeFood({ id: `cf-${i}`, name: `Food ${i}` })
    );
    const pageTwo = [makeFood({ id: "cf-50", name: "Food 50" })];
    mockList.mockImplementation((_limit: number, offset: number) =>
      Promise.resolve({
        common_foods: offset === 0 ? pageOne : pageTwo,
        total: 51,
      })
    );
    mockDelete.mockResolvedValue(undefined);
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    render(<CommonFoodsPage />);

    await screen.findByText("Page 1 of 2");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Page 2 of 2");

    // Delete the only row on page 2 -> should reload page 1 (offset 0).
    fireEvent.click(screen.getByTestId("common-food-delete"));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("cf-50"));
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith(50, 0)
    );
    confirmSpy.mockRestore();
  });

  it("renders a feature-off dead end (no raw 404) when meal intelligence is off", async () => {
    mockList.mockRejectedValue(
      new MealApiError(404, "Meal intelligence is not enabled.")
    );
    render(<CommonFoodsPage />);

    expect(await screen.findByTestId("meal-feature-off")).toBeInTheDocument();
    expect(screen.queryByTestId("common-food-row")).not.toBeInTheDocument();
  });
});
