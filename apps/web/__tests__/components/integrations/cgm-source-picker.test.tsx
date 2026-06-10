/**
 * CgmSourcePicker Tests (Story 43.10)
 *
 * - Auto-hides when the user has zero or one CGM source.
 * - Renders an option per CGM source when more than one exists.
 * - PUT round-trip refreshes the hook so roles reflect the new pick.
 */

import { CgmSourcePicker } from "@/components/integrations/cgm-source-picker";
import {
  type CgmSourcesResponse,
  getCgmSources,
  updatePrimaryCgmSource,
} from "@/lib/api";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

jest.mock("@/lib/api", () => ({
  getCgmSources: jest.fn(),
  updatePrimaryCgmSource: jest.fn(),
}));

const mockGet = getCgmSources as jest.MockedFunction<typeof getCgmSources>;
const mockUpdate = updatePrimaryCgmSource as jest.MockedFunction<
  typeof updatePrimaryCgmSource
>;

function makeResponse(
  overrides: Partial<CgmSourcesResponse> = {}
): CgmSourcesResponse {
  return {
    sources: [
      { source: "dexcom", label: "Dexcom", role: "primary", kind: "dexcom" },
      {
        source: "nightscout:abc",
        label: "Loop NS",
        role: "secondary",
        kind: "nightscout",
      },
    ],
    primary_source: "dexcom",
    multiple_sources: true,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("CgmSourcePicker", () => {
  it("auto-hides when only one CGM source exists", async () => {
    mockGet.mockResolvedValue(
      makeResponse({
        sources: [
          { source: "dexcom", label: "Dexcom", role: "primary", kind: "dexcom" },
        ],
        multiple_sources: false,
      })
    );
    const { container } = render(<CgmSourcePicker />);
    // After the fetch settles the component renders nothing (it hides for a
    // single source). Poll until the loading skeleton clears to empty.
    await waitFor(() => {
      expect(container).toBeEmptyDOMElement();
    });
    expect(screen.queryByTestId("cgm-source-picker")).not.toBeInTheDocument();
  });

  it("renders an option per CGM source when multiple exist", async () => {
    mockGet.mockResolvedValue(makeResponse());
    render(<CgmSourcePicker />);
    await waitFor(() => {
      expect(screen.getByTestId("cgm-source-picker")).toBeInTheDocument();
    });
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("dexcom");
    expect(screen.getByRole("option", { name: "Dexcom" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Loop NS" })).toBeInTheDocument();
  });

  it("PUTs the chosen source and refreshes", async () => {
    mockGet
      .mockResolvedValueOnce(makeResponse())
      .mockResolvedValueOnce(
        makeResponse({
          primary_source: "nightscout:abc",
          sources: [
            {
              source: "dexcom",
              label: "Dexcom",
              role: "secondary",
              kind: "dexcom",
            },
            {
              source: "nightscout:abc",
              label: "Loop NS",
              role: "primary",
              kind: "nightscout",
            },
          ],
        })
      );
    mockUpdate.mockResolvedValue({ primary_source: "nightscout:abc" });

    render(<CgmSourcePicker />);
    await waitFor(() =>
      expect(screen.getByTestId("cgm-source-picker")).toBeInTheDocument()
    );

    await act(async () => {
      fireEvent.change(screen.getByRole("combobox"), {
        target: { value: "nightscout:abc" },
      });
    });

    expect(mockUpdate).toHaveBeenCalledWith("nightscout:abc");
    await waitFor(() => {
      const select = screen.getByRole("combobox") as HTMLSelectElement;
      expect(select.value).toBe("nightscout:abc");
    });
  });

  it("surfaces an error when the post-PUT refresh fails", async () => {
    // PUT succeeds but the re-read rejects -> the picker must show an error
    // rather than silently reporting success on stale UI.
    mockGet
      .mockResolvedValueOnce(makeResponse())
      .mockRejectedValueOnce(new Error("network down"));
    mockUpdate.mockResolvedValue({ primary_source: "nightscout:abc" });

    render(<CgmSourcePicker />);
    await waitFor(() =>
      expect(screen.getByTestId("cgm-source-picker")).toBeInTheDocument()
    );

    await act(async () => {
      fireEvent.change(screen.getByRole("combobox"), {
        target: { value: "nightscout:abc" },
      });
    });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("network down");
    });
  });
});
