package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestIsCaptureRedirect_MatchesCarePartnerWithCode(t *testing.T) {
	for _, status := range []int{301, 302, 303, 307, 308} {
		if !isCaptureRedirect(status, "com.medtronic.carepartner:/sso?code=abc&state=xyz") {
			t.Errorf("expected match for status %d", status)
		}
	}
}

func TestIsCaptureRedirect_RejectsNonRedirectStatus(t *testing.T) {
	if isCaptureRedirect(200, "com.medtronic.carepartner:/sso?code=abc") {
		t.Error("200 must not match")
	}
	if isCaptureRedirect(404, "com.medtronic.carepartner:/sso?code=abc") {
		t.Error("404 must not match")
	}
}

func TestIsCaptureRedirect_RejectsOtherSchemes(t *testing.T) {
	cases := []string{
		"https://carelink-login.minimed.com/u/login",
		"com.medtronic.carepartner:/sso?error=denied", // no code=
		"",
	}
	for _, c := range cases {
		if isCaptureRedirect(302, c) {
			t.Errorf("must not match: %q", c)
		}
	}
}

func TestExtractLocationHeader_CaseInsensitive(t *testing.T) {
	headers := map[string]interface{}{
		"Content-Type": "text/html",
		"Location":     "com.medtronic.carepartner:/sso?code=ok",
	}
	if got := extractLocationHeader(headers); got != "com.medtronic.carepartner:/sso?code=ok" {
		t.Errorf("title-case Location: got %q", got)
	}
	headers2 := map[string]interface{}{"location": "lower-case"}
	if got := extractLocationHeader(headers2); got != "lower-case" {
		t.Errorf("lower-case location: got %q", got)
	}
	if got := extractLocationHeader(map[string]interface{}{"X-Other": "v"}); got != "" {
		t.Errorf("missing -> %q (want empty)", got)
	}
}

func TestExtractLocationHeader_IgnoresNonStringValues(t *testing.T) {
	headers := map[string]interface{}{"location": 123} // chromedp can hand back non-string defensively
	if got := extractLocationHeader(headers); got != "" {
		t.Errorf("non-string -> %q (want empty)", got)
	}
}

func TestParseFlags_AcceptsRequiredFlags(t *testing.T) {
	got, err := parseFlags([]string{
		"--api", "https://x.test/",
		"--pair", "tok",
		"--username", "u",
	})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if got.apiURL != "https://x.test" {
		t.Errorf("apiURL trailing slash not stripped: %q", got.apiURL)
	}
	if got.pair != "tok" || got.username != "u" {
		t.Errorf("required flags: %+v", got)
	}
	if got.region != "US" {
		t.Errorf("default region: %q", got.region)
	}
}

func TestParseFlags_NormalisesRegionUpper(t *testing.T) {
	got, err := parseFlags([]string{
		"--api", "https://x.test",
		"--pair", "tok",
		"--username", "u",
		"--region", "eu",
		"--browser", "brave-browser",
	})
	if err != nil {
		t.Fatalf("err: %v", err)
	}
	if got.region != "EU" {
		t.Errorf("region upper: %q", got.region)
	}
	if got.browser != "brave-browser" {
		t.Errorf("browser flag: %q", got.browser)
	}
}

func TestParseFlags_RejectsMissingRequired(t *testing.T) {
	cases := [][]string{
		{},
		{"--api", "https://x.test"},
		{"--api", "https://x.test", "--pair", "t"},
		{"--pair", "t", "--username", "u"},
	}
	for _, c := range cases {
		if _, err := parseFlags(c); err == nil {
			t.Errorf("expected err for %v", c)
		}
	}
}

func TestBrowserExecCandidates_IncludeEdgeAndBrave(t *testing.T) {
	joined := strings.Join(browserExecCandidates(), "\n")
	for _, want := range []string{"brave", "edge"} {
		if !strings.Contains(strings.ToLower(joined), want) {
			t.Errorf("browser candidates should include %s; got %q", want, joined)
		}
	}
}

func TestFindBrowserExecPath_AcceptsExplicitExecutable(t *testing.T) {
	exe, err := os.Executable()
	if err != nil {
		t.Fatalf("os.Executable: %v", err)
	}
	got, err := findBrowserExecPath(exe)
	if err != nil {
		t.Fatalf("findBrowserExecPath(%q): %v", exe, err)
	}
	if got != exe {
		t.Errorf("explicit executable path: got %q want %q", got, exe)
	}
}

func TestFindBrowserExecPath_RejectsMissingExplicitBrowser(t *testing.T) {
	_, err := findBrowserExecPath("/definitely/not/a/browser")
	if err == nil {
		t.Fatal("expected missing browser error")
	}
	if !strings.Contains(err.Error(), "was not found") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestBrowserExecCandidatesFor_Linux(t *testing.T) {
	got := browserExecCandidatesFor("linux", "/home/u", func(string) string { return "" })
	want := []string{
		"google-chrome", "google-chrome-stable", "chrome",
		"chromium", "chromium-browser",
		"brave-browser", "brave",
		"microsoft-edge", "microsoft-edge-stable", "msedge",
	}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Errorf("linux candidates:\n got %q\nwant %q", got, want)
	}
}

func TestBrowserExecCandidatesFor_Darwin(t *testing.T) {
	got := browserExecCandidatesFor("darwin", "/Users/jo", func(string) string { return "" })
	joined := strings.Join(got, "\n")
	for _, want := range []string{
		"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
		"/Applications/Chromium.app/Contents/MacOS/Chromium",
		"/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
		"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
		"/Users/jo/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
		"brave-browser", "microsoft-edge",
	} {
		if !strings.Contains(joined, want) {
			t.Errorf("darwin candidates missing %q\ngot %q", want, joined)
		}
	}
	// With no home dir, only the system /Applications prefix should appear.
	for _, c := range browserExecCandidatesFor("darwin", "", func(string) string { return "" }) {
		if strings.HasPrefix(c, "/Users") {
			t.Errorf("unexpected per-user path with empty home: %q", c)
		}
	}
}

func TestBrowserExecCandidatesFor_Windows(t *testing.T) {
	env := map[string]string{
		"LOCALAPPDATA":      `C:\Users\jo\AppData\Local`,
		"PROGRAMFILES":      `C:\Program Files`,
		"PROGRAMFILES(X86)": `C:\Program Files (x86)`,
	}
	got := browserExecCandidatesFor("windows", "", func(k string) string { return env[k] })
	joined := strings.Join(got, "\n")
	for _, base := range []string{env["LOCALAPPDATA"], env["PROGRAMFILES"], env["PROGRAMFILES(X86)"]} {
		for _, want := range []string{
			filepath.Join(base, "Google", "Chrome", "Application", "chrome.exe"),
			filepath.Join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
			filepath.Join(base, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
		} {
			if !strings.Contains(joined, want) {
				t.Errorf("windows candidates missing %q\ngot %q", want, joined)
			}
		}
	}
	for _, want := range []string{"chrome.exe", "msedge.exe", "brave.exe", "chromium.exe"} {
		if !strings.Contains(joined, want) {
			t.Errorf("windows bare fallback missing %q", want)
		}
	}
	// Empty install-root vars must be skipped, not joined into bogus paths.
	none := browserExecCandidatesFor("windows", "", func(string) string { return "" })
	if strings.Join(none, ",") != "chrome.exe,msedge.exe,brave.exe,chromium.exe" {
		t.Errorf("windows with no env should yield only bare names; got %q", none)
	}
}

func TestExecutablePath_LookPathBranch(t *testing.T) {
	dir := t.TempDir()
	full := filepath.Join(dir, "fake-browser")
	if err := os.WriteFile(full, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write fake browser: %v", err)
	}
	t.Setenv("PATH", dir)
	got, ok := executablePath("fake-browser")
	if !ok {
		t.Fatal("expected bare command to resolve via PATH")
	}
	if got != full {
		t.Errorf("LookPath result: got %q want %q", got, full)
	}
}

func TestExecutablePath_RejectsDirectoryAndMissing(t *testing.T) {
	if _, ok := executablePath(t.TempDir()); ok {
		t.Error("a directory must not resolve as an executable")
	}
	if _, ok := executablePath("/no/such/browser/binary"); ok {
		t.Error("a missing absolute path must not resolve")
	}
	if _, ok := executablePath(""); ok {
		t.Error("empty candidate must not resolve")
	}
}

func TestFindBrowserExecPath_AutoDetectResolvesOnPath(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("auto-detect candidate names are OS-specific; PATH-injection test is linux-only")
	}
	dir := t.TempDir()
	full := filepath.Join(dir, "google-chrome") // first linux candidate
	if err := os.WriteFile(full, []byte("#!/bin/sh\n"), 0o755); err != nil {
		t.Fatalf("write fake browser: %v", err)
	}
	t.Setenv("PATH", dir)
	got, err := findBrowserExecPath("")
	if err != nil {
		t.Fatalf("auto-detect should resolve a browser on PATH: %v", err)
	}
	if got != full {
		t.Errorf("auto-detect path: got %q want %q", got, full)
	}
}

// Asserts findBrowserExecPath's own contract. Note captureRedirect deliberately
// swallows this error on auto-detect (browser == "") and falls through to
// chromedp's findExecPath; the message a no-browser user actually sees comes
// from the reworded network.Enable() error in captureRedirect.
func TestFindBrowserExecPath_NoBrowserReturnsActionableError(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("relies on linux candidates being bare PATH names; other OSes probe absolute paths")
	}
	t.Setenv("PATH", t.TempDir()) // empty dir: no candidate resolves
	_, err := findBrowserExecPath("")
	if err == nil {
		t.Fatal("expected no-browser error")
	}
	for _, want := range []string{"no supported Chromium-family browser", "--browser"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error %q should mention %q", err.Error(), want)
		}
	}
}
