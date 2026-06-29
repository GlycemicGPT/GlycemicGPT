import { twMerge } from "./twMerge";

describe("twMerge", () => {
  it("merges conditional class values", () => {
    expect(twMerge("base", false && "hidden", ["visible"])).toBe("base visible");
  });

  it("normalizes conflicting Tailwind classes", () => {
    expect(twMerge("px-2 text-slate-500", "px-4 text-foreground-primary")).toBe(
      "px-4 text-foreground-primary",
    );
  });

  it("normalizes local font typography classes", () => {
    expect(twMerge("font_header_1", "font_body_1")).toBe("font_body_1");
    expect(twMerge("font_metric_label", "font_metric_caption")).toBe("font_metric_caption");
  });

  it("normalizes local font face classes", () => {
    expect(twMerge("font_poppins", "font_jetbrains_mono")).toBe("font_jetbrains_mono");
  });

  it("keeps local font weight and tracking classes separate from typography", () => {
    expect(twMerge("font_header_1 font_regular font_normal", "font_bold font_medium")).toBe(
      "font_header_1 font_bold font_medium",
    );
  });

  it("normalizes prefixed font style classes", () => {
    expect(twMerge("font_ui_label", "font_ui_caption")).toBe("font_ui_caption");
  });
});
