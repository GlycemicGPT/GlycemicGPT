/**
 * Tests for MealPhoto: renders the fetched photo, falls back to the placeholder
 * when it can't be loaded, and revokes the object URL on unmount.
 */

import { render, screen } from "@testing-library/react";

const mockPhoto = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  fetchFoodRecordPhotoObjectUrl: (...args: unknown[]) => mockPhoto(...args),
}));

import { MealPhoto } from "@/components/meals/meal-photo";

describe("MealPhoto", () => {
  beforeEach(() => {
    mockPhoto.mockReset();
    // jsdom doesn't implement these; the component revokes blobs on unmount.
    (URL as unknown as { revokeObjectURL: jest.Mock }).revokeObjectURL =
      jest.fn();
  });

  it("renders the fetched photo on success", async () => {
    mockPhoto.mockResolvedValue("blob:abc123");
    render(<MealPhoto recordId="rec-1" size="lg" />);
    const img = await screen.findByTestId("meal-photo");
    expect(img).toHaveAttribute("src", "blob:abc123");
    expect(mockPhoto).toHaveBeenCalledWith("rec-1");
  });

  it("falls back to the placeholder when the photo can't be loaded", async () => {
    mockPhoto.mockRejectedValue(new Error("404"));
    render(<MealPhoto recordId="rec-1" size="sm" />);
    expect(
      await screen.findByTestId("meal-photo-placeholder")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("meal-photo")).not.toBeInTheDocument();
  });

  it("revokes the object URL on unmount", async () => {
    mockPhoto.mockResolvedValue("blob:xyz");
    const { unmount } = render(<MealPhoto recordId="rec-1" />);
    await screen.findByTestId("meal-photo");
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:xyz");
  });
});
