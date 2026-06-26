/**
 * Tests for the web meal upload control: happy path calls onUploaded, and the
 * vision-unavailable / no-provider / feature-off responses surface the matching
 * dead-end state and NEVER a fabricated estimate.
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

const mockUpload = jest.fn();
jest.mock("@/lib/api", () => ({
  __esModule: true,
  ...jest.requireActual("@/lib/api"),
  uploadFoodRecord: (...args: unknown[]) => mockUpload(...args),
}));

const mockCompress = jest.fn();
jest.mock("@/lib/image-compress", () => ({
  __esModule: true,
  ...jest.requireActual("@/lib/image-compress"),
  compressImageToJpeg: (...args: unknown[]) => mockCompress(...args),
}));

import { MealUpload } from "@/components/meals/meal-upload";
import { MealApiError } from "@/lib/api";

function pickFile() {
  const file = new File(["jpeg-bytes"], "meal.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByTestId("meal-file-input"), {
    target: { files: [file] },
  });
}

describe("MealUpload", () => {
  beforeEach(() => {
    mockUpload.mockReset();
    mockCompress.mockReset();
    mockCompress.mockResolvedValue(new Blob(["x"], { type: "image/jpeg" }));
  });

  it("compresses then uploads and calls onUploaded on success", async () => {
    const record = { id: "new-rec" };
    mockUpload.mockResolvedValue(record);
    const onUploaded = jest.fn();

    render(<MealUpload onUploaded={onUploaded} />);
    pickFile();

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(record));
    expect(mockCompress).toHaveBeenCalledTimes(1);
  });

  it("surfaces a vision-unavailable dead end and does not call onUploaded", async () => {
    mockUpload.mockRejectedValue(
      new MealApiError(422, "Vision is not available on your current AI provider.")
    );
    const onUploaded = jest.fn();

    render(<MealUpload onUploaded={onUploaded} />);
    pickFile();

    expect(
      await screen.findByTestId("meal-vision-unavailable")
    ).toBeInTheDocument();
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it("surfaces a no-provider dead end", async () => {
    mockUpload.mockRejectedValue(
      new MealApiError(404, "No AI provider configured.")
    );
    render(<MealUpload onUploaded={jest.fn()} />);
    pickFile();
    expect(await screen.findByTestId("meal-no-provider")).toBeInTheDocument();
  });

  it("calls onFeatureOff when the upload reveals the feature is disabled", async () => {
    mockUpload.mockRejectedValue(
      new MealApiError(404, "Meal intelligence is not enabled.")
    );
    const onFeatureOff = jest.fn();
    render(<MealUpload onUploaded={jest.fn()} onFeatureOff={onFeatureOff} />);
    pickFile();
    await screen.findByTestId("meal-feature-off");
    expect(onFeatureOff).toHaveBeenCalled();
  });
});
