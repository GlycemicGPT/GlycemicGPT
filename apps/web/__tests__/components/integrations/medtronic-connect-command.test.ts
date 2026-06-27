/**
 * buildHelperCommand — the copy-paste command builder for the Medtronic
 * CarePartner Connect helper. Covers the optional --browser passthrough and its
 * per-shell quoting (issue #815: let custom-install Brave/Edge/Chromium users
 * point the helper at their own binary from the web flow).
 */

import { buildHelperCommand } from "@/components/integrations/medtronic-connect-card";

const SH_URL = "https://gly.example.com/api/integrations/medtronic/connect/install/abcd.sh";
const PS_URL = "https://gly.example.com/api/integrations/medtronic/connect/install/abcd.ps1";

describe("buildHelperCommand", () => {
  describe("no custom browser (default auto-detect)", () => {
    it("bash: pipes the install script straight into bash", () => {
      expect(buildHelperCommand(SH_URL, "linux-mac", "")).toBe(
        `curl -fsSL '${SH_URL}' | bash`
      );
    });

    it("PowerShell: pipes the install script into iex", () => {
      expect(buildHelperCommand(PS_URL, "windows", "")).toBe(
        `iwr '${PS_URL}' -UseBasicParsing | iex`
      );
    });

    it("treats a whitespace-only path as no custom browser", () => {
      expect(buildHelperCommand(SH_URL, "linux-mac", "   ")).toBe(
        `curl -fsSL '${SH_URL}' | bash`
      );
    });
  });

  describe("custom browser passthrough", () => {
    it("bash: forwards --browser via `bash -s --`", () => {
      expect(buildHelperCommand(SH_URL, "linux-mac", "/usr/bin/brave-browser")).toBe(
        `curl -fsSL '${SH_URL}' | bash -s -- --browser '/usr/bin/brave-browser'`
      );
    });

    it("bash: single-quotes a path containing spaces (macOS app bundle)", () => {
      const macBrave =
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";
      expect(buildHelperCommand(SH_URL, "linux-mac", macBrave)).toBe(
        `curl -fsSL '${SH_URL}' | bash -s -- --browser '${macBrave}'`
      );
    });

    it("bash: escapes an embedded single quote with the POSIX '\\'' idiom", () => {
      const tricky = "/opt/o'brien/chrome";
      const cmd = buildHelperCommand(SH_URL, "linux-mac", tricky);
      expect(cmd).toBe(
        `curl -fsSL '${SH_URL}' | bash -s -- --browser '/opt/o'\\''brien/chrome'`
      );
    });

    it("PowerShell: runs a script block so trailing args reach the helper", () => {
      const winBrave =
        "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe";
      expect(buildHelperCommand(PS_URL, "windows", winBrave)).toBe(
        `& ([scriptblock]::Create((iwr '${PS_URL}' -UseBasicParsing).Content)) --browser '${winBrave}'`
      );
    });

    it("PowerShell: doubles an embedded single quote (full command pinned)", () => {
      const tricky = "C:\\o'brien\\brave.exe";
      expect(buildHelperCommand(PS_URL, "windows", tricky)).toBe(
        `& ([scriptblock]::Create((iwr '${PS_URL}' -UseBasicParsing).Content)) --browser 'C:\\o''brien\\brave.exe'`
      );
    });

    it("trims surrounding whitespace from the path before quoting", () => {
      expect(buildHelperCommand(SH_URL, "linux-mac", "  /usr/bin/chromium  ")).toBe(
        `curl -fsSL '${SH_URL}' | bash -s -- --browser '/usr/bin/chromium'`
      );
    });
  });

  describe("URL quoting (the instance URL is a user-editable field)", () => {
    it("bash: POSIX-escapes a single quote in the URL", () => {
      const url = "https://exa'mple.com/api/integrations/medtronic/connect/install/abcd.sh";
      expect(buildHelperCommand(url, "linux-mac", "")).toBe(
        `curl -fsSL 'https://exa'\\''mple.com/api/integrations/medtronic/connect/install/abcd.sh' | bash`
      );
    });

    it("PowerShell: doubles a single quote in the URL", () => {
      const url = "https://exa'mple.com/api/integrations/medtronic/connect/install/abcd.ps1";
      expect(buildHelperCommand(url, "windows", "")).toBe(
        `iwr 'https://exa''mple.com/api/integrations/medtronic/connect/install/abcd.ps1' -UseBasicParsing | iex`
      );
    });
  });
});
