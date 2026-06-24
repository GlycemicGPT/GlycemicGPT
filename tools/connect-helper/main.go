// glycemicgpt-connect: the one-time desktop helper that completes the Medtronic
// CareLink CarePartner Connect login locally and hands the resulting one-shot
// authorization code to a GlycemicGPT instance over its API.
//
// WHY THIS EXISTS
//
//	Medtronic's CarePartner login can only be completed interactively in a
//	browser, and on success Auth0 redirects to a *mobile-app* URL scheme
//	(com.medtronic.carepartner:/sso?code=...) that no web app and no server
//	can receive. So a tiny native helper on the user's machine drives the
//	login in their own installed Chrome (or Edge / Brave / Chromium -- any
//	Chromium-protocol-compatible browser), intercepts that 302 at the
//	DevTools-Protocol layer, and POSTs the code to the user's GlycemicGPT
//	backend. The backend does the actual Auth0 code -> refresh-token exchange
//	server-side, so the refresh token NEVER reaches this binary.
//
// WHAT IT NEVER SEES
//   - The user's CareLink password (typed directly into Medtronic's page).
//   - The user's GlycemicGPT password (the pair token only authorizes the
//     two Connect-handshake endpoints for that one user).
//   - The Medtronic refresh token (the backend does the code exchange).
//
// Statically linked, no Go runtime needed at the user's end. Built per OS/arch
// by the multi-stage Dockerfile in apps/api/, baked into the API image, and
// served by /api/integrations/medtronic/connect/helper-binary (which is itself
// gated by the user's active pair token).
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/chromedp/cdproto/network"
	"github.com/chromedp/chromedp"
)

const (
	// The mobile-app custom URL scheme Auth0 redirects to on successful
	// CarePartner login. Auth0 picked it as the registered redirect_uri; we
	// neither chose nor can change it. We just watch for it at the network
	// layer before the browser tries (and fails) to navigate.
	redirectScheme = "com.medtronic.carepartner:"

	// Header the GlycemicGPT API uses to accept the helper-side pair token on
	// /authorize-url and /exchange. Mirror of
	// connect_pairing.CONNECT_PAIR_TOKEN_HEADER on the Python side.
	pairTokenHeader = "X-Connect-Pair-Token"

	authorizeURLPath = "/api/integrations/medtronic/connect/authorize-url"
	exchangeURLPath  = "/api/integrations/medtronic/connect/exchange"
)

type flags struct {
	apiURL   string
	pair     string
	username string
	region   string
	timeout  time.Duration
	headless bool
	browser  string
}

// parseFlags is split out so it can be unit-tested without a running browser.
func parseFlags(args []string) (*flags, error) {
	fs := flag.NewFlagSet("glycemicgpt-connect", flag.ContinueOnError)
	var (
		apiURL   = fs.String("api", "", "Your GlycemicGPT base URL (required)")
		pair     = fs.String("pair", "", "Pairing token from the GlycemicGPT web card (required)")
		username = fs.String("username", "", "Your CareLink username (required)")
		region   = fs.String("region", "US", "CarePartner region: US, or EU for non-US (UK/EU/AU/ZA/...)")
		timeout  = fs.Duration("timeout", 5*time.Minute, "How long to wait for you to finish the browser login")
		headless = fs.Bool("headless", false, "Run the browser headless (NOT recommended -- you must solve a captcha)")
		browser  = fs.String("browser", "", "Optional browser executable path or command (Chrome, Edge, Brave, or Chromium)")
	)
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if *apiURL == "" || *pair == "" || *username == "" {
		return nil, errors.New("--api, --pair, and --username are required")
	}
	return &flags{
		apiURL:   strings.TrimRight(*apiURL, "/"),
		pair:     *pair,
		username: *username,
		region:   strings.ToUpper(*region),
		timeout:  *timeout,
		headless: *headless,
		browser:  strings.TrimSpace(*browser),
	}, nil
}

// isCaptureRedirect identifies the one HTTP response that carries the auth
// code on its Location header: a 30x response whose Location starts with the
// CarePartner custom scheme AND contains a `code=` query parameter. Split out
// so it's unit-testable without spinning up a browser.
func isCaptureRedirect(status int, location string) bool {
	if status < 300 || status >= 400 {
		return false
	}
	if !strings.HasPrefix(location, redirectScheme) {
		return false
	}
	return strings.Contains(location, "code=")
}

// extractLocationHeader pulls a Location header from the case-insensitive map
// chromedp hands back on Network.responseReceived (chromedp uses
// map[string]interface{} so we have to be defensive).
func extractLocationHeader(headers map[string]interface{}) string {
	for k, v := range headers {
		if strings.EqualFold(k, "location") {
			if s, ok := v.(string); ok {
				return s
			}
		}
	}
	return ""
}

type authorizeResponse struct {
	AuthorizeURL string `json:"authorize_url"`
	PKCESession  string `json:"pkce_session"`
	State        string `json:"state"`
}

func getAuthorize(ctx context.Context, f *flags) (*authorizeResponse, error) {
	u := f.apiURL + authorizeURLPath + "?region=" + f.region
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set(pairTokenHeader, f.pair)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("contacting %s: %w", f.apiURL, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusUnauthorized {
		return nil, errors.New("pairing token was rejected (expired or already used) -- reissue it in GlycemicGPT and run again")
	}
	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("authorize-url returned %d: %s", resp.StatusCode, string(body))
	}
	var out authorizeResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("decoding authorize-url response: %w", err)
	}
	if out.AuthorizeURL == "" || out.PKCESession == "" {
		return nil, errors.New("authorize-url response missing required fields")
	}
	return &out, nil
}

// browserExecCandidates returns the ordered list of Chromium-family browser
// executables to probe when the user did not pass --browser. It reads the real
// host environment; the pure logic lives in browserExecCandidatesFor so each
// OS branch can be table-tested from a single-platform runner.
func browserExecCandidates() []string {
	home, _ := os.UserHomeDir()
	return browserExecCandidatesFor(runtime.GOOS, home, os.Getenv)
}

// browserExecCandidatesFor is the pure core of browserExecCandidates: no direct
// os calls, so the darwin/windows branches (unreachable when `go test` runs on
// Linux) can still be asserted in unit tests. `home` is the user's home dir ("",
// if unknown) and `getenv` resolves Windows install-root variables.
func browserExecCandidatesFor(goos, home string, getenv func(string) string) []string {
	switch goos {
	case "darwin":
		homes := []string{"/Applications"}
		if home != "" {
			homes = append(homes, filepath.Join(home, "Applications"))
		}
		apps := []string{
			"Google Chrome.app/Contents/MacOS/Google Chrome",
			"Chromium.app/Contents/MacOS/Chromium",
			"Brave Browser.app/Contents/MacOS/Brave Browser",
			"Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
		}
		out := make([]string, 0, len(homes)*len(apps)+4)
		for _, h := range homes {
			for _, app := range apps {
				out = append(out, filepath.Join(h, app))
			}
		}
		return append(out, "google-chrome", "chromium", "brave-browser", "microsoft-edge")
	case "windows":
		var out []string
		for _, base := range []string{getenv("LOCALAPPDATA"), getenv("PROGRAMFILES"), getenv("PROGRAMFILES(X86)")} {
			if base == "" {
				continue
			}
			out = append(out,
				filepath.Join(base, "Google", "Chrome", "Application", "chrome.exe"),
				filepath.Join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
				filepath.Join(base, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
			)
		}
		return append(out, "chrome.exe", "msedge.exe", "brave.exe", "chromium.exe")
	default:
		return []string{
			"google-chrome", "google-chrome-stable", "chrome",
			"chromium", "chromium-browser",
			"brave-browser", "brave",
			"microsoft-edge", "microsoft-edge-stable", "msedge",
		}
	}
}

// executablePath resolves a --browser value (or an auto-detect candidate) to a
// concrete executable. A value containing a path separator is treated as a
// filesystem path and stat'd directly (rejecting directories); a bare name is
// looked up on PATH. The bool reports whether a usable executable was found.
func executablePath(candidate string) (string, bool) {
	if candidate == "" {
		return "", false
	}
	if filepath.IsAbs(candidate) || strings.ContainsAny(candidate, `/\`) {
		info, err := os.Stat(candidate)
		if err == nil && !info.IsDir() {
			return candidate, true
		}
		return "", false
	}
	if path, err := exec.LookPath(candidate); err == nil {
		return path, true
	}
	return "", false
}

// findBrowserExecPath resolves which browser to drive. An explicit --browser
// that can't be resolved is a hard error (the user named a specific binary);
// with no request it probes the per-OS candidates and returns an actionable
// error naming the supported browsers and the --browser escape hatch.
func findBrowserExecPath(requested string) (string, error) {
	if requested != "" {
		if path, ok := executablePath(requested); ok {
			return path, nil
		}
		return "", fmt.Errorf("browser %q was not found or is not executable", requested)
	}
	for _, candidate := range browserExecCandidates() {
		if path, ok := executablePath(candidate); ok {
			return path, nil
		}
	}
	return "", errors.New("no supported Chromium-family browser found (install Chrome, Edge, Brave, or Chromium, or pass --browser /path/to/browser)")
}

// captureRedirect launches the user's installed Chromium-family browser at the
// supplied authorize_url, lets the user complete the CareLink login + captcha,
// and returns the captured 302 Location (custom-scheme URL carrying the code).
func captureRedirect(ctx context.Context, authorizeURL string, headless bool, browser string) (string, error) {
	// Use a fresh temporary user-data dir so we don't touch the user's normal
	// browser profile.
	tmp, err := os.MkdirTemp("", "glycemicgpt-connect-*")
	if err != nil {
		return "", fmt.Errorf("creating temp user-data dir: %w", err)
	}
	defer os.RemoveAll(tmp)

	var opts []chromedp.ExecAllocatorOption
	if browserPath, err := findBrowserExecPath(browser); err == nil {
		opts = append(opts, chromedp.ExecPath(browserPath))
	} else if browser != "" {
		// An explicit --browser we couldn't resolve is fatal: never silently
		// launch a different browser than the one the user named.
		return "", err
	}
	// If auto-detection found nothing (browser == "" and no candidate matched),
	// fall through WITHOUT an ExecPath on purpose: chromedp's own findExecPath
	// covers a few targets our candidate list omits (headless_shell, the Chrome
	// beta/unstable channels, some absolute/snap paths). If that also fails, the
	// actionable error surfaces at the network.Enable() call below.

	opts = append(opts, chromedp.DefaultExecAllocatorOptions[:]...)
	opts = append(opts,
		chromedp.Flag("headless", headless),
		chromedp.UserDataDir(tmp),
		chromedp.NoFirstRun,
		chromedp.NoDefaultBrowserCheck,
	)
	allocCtx, cancelAlloc := chromedp.NewExecAllocator(ctx, opts...)
	defer cancelAlloc()
	browserCtx, cancelBrowser := chromedp.NewContext(allocCtx)
	defer cancelBrowser()

	captured := make(chan string, 1)
	chromedp.ListenTarget(browserCtx, func(ev interface{}) {
		switch e := ev.(type) {
		case *network.EventResponseReceived:
			if e.Response == nil {
				return
			}
			loc := extractLocationHeader(e.Response.Headers)
			if isCaptureRedirect(int(e.Response.Status), loc) {
				select {
				case captured <- loc:
				default:
				}
			}
		case *network.EventRequestWillBeSent:
			// Auth0 may report the redirect via the redirectResponse on the
			// next request that the browser would have made; catch that too in
			// case ResponseReceived isn't fired for the custom scheme.
			if e.RedirectResponse == nil {
				return
			}
			loc := extractLocationHeader(e.RedirectResponse.Headers)
			if isCaptureRedirect(int(e.RedirectResponse.Status), loc) {
				select {
				case captured <- loc:
				default:
				}
			}
		}
	})

	// Enable the Network domain so the events above actually fire.
	if err := chromedp.Run(browserCtx, network.Enable()); err != nil {
		// network.Enable is the first command that actually launches the
		// browser, so a failure here almost always means no Chromium-family
		// browser could be started -- not that DevTools itself is broken.
		return "", fmt.Errorf("could not start a Chromium-family browser (Chrome, Edge, Brave, or Chromium); if yours is installed in a custom location, pass --browser /path/to/browser: %w", err)
	}

	// Initial navigation: don't fail the run on a transient error (the post-
	// login custom-scheme nav legitimately fails too -- it's how we capture).
	// User-facing copy lives in run() so this function stays pure plumbing.
	_ = chromedp.Run(browserCtx, chromedp.Navigate(authorizeURL))

	select {
	case loc := <-captured:
		return loc, nil
	case <-browserCtx.Done():
		if errors.Is(browserCtx.Err(), context.DeadlineExceeded) {
			return "", errors.New("timed out waiting for CareLink sign-in")
		}
		return "", browserCtx.Err()
	}
}

// exchangeRequest is the v1 (patient-self) payload: a user connecting their
// OWN Medtronic account. The follower / care-partner case (logging in to follow
// someone else's pump) additionally needs role + patient_id; the backend
// /exchange accepts them, but plumbing them through the CLI plus a way to pick
// the patient is a tracked follow-up, not in v1. See README.md.
type exchangeRequest struct {
	PKCESession string `json:"pkce_session"`
	RedirectURL string `json:"redirect_url"`
	Username    string `json:"username"`
}

type exchangeResponse struct {
	Connected bool   `json:"connected"`
	Status    string `json:"status"`
	Region    string `json:"region"`
}

func postExchange(ctx context.Context, f *flags, pkce, redirectURL string) (*exchangeResponse, error) {
	body, err := json.Marshal(exchangeRequest{
		PKCESession: pkce,
		RedirectURL: redirectURL,
		Username:    f.username,
	})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, f.apiURL+exchangeURLPath, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set(pairTokenHeader, f.pair)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("contacting %s: %w", f.apiURL, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusUnauthorized {
		return nil, errors.New("the CareLink login could not be completed (the code may have expired) -- run this again and paste/sign in promptly")
	}
	if resp.StatusCode >= 400 {
		buf, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("exchange returned %d: %s", resp.StatusCode, string(buf))
	}
	var out exchangeResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("decoding exchange response: %w", err)
	}
	return &out, nil
}

func run() error {
	cli, err := parseFlags(os.Args[1:])
	if err != nil {
		return err
	}

	printBanner()
	fmt.Printf("  Server  %s\n", cli.apiURL)
	fmt.Printf("  Region  %s     User  %s\n\n", cli.region, cli.username)

	ctx, cancel := context.WithTimeout(context.Background(), cli.timeout)
	defer cancel()

	fmt.Println("  [1/3]  Pairing with your GlycemicGPT server...")
	start, err := getAuthorize(ctx, cli)
	if err != nil {
		return err
	}

	fmt.Println("  [2/3]  Opening your browser  -  sign in to CareLink (solve the captcha if it appears)")
	redirect, err := captureRedirect(ctx, start.AuthorizeURL, cli.headless, cli.browser)
	if err != nil {
		return err
	}

	fmt.Println("  [3/3]  Saving credential on your GlycemicGPT server...")
	resp, err := postExchange(ctx, cli, start.PKCESession, redirect)
	if err != nil {
		return err
	}
	fmt.Printf("\n  ✓ Connected. GlycemicGPT will now sync your Medtronic data automatically.\n")
	fmt.Printf("    status=%s region=%s\n", resp.Status, resp.Region)
	fmt.Println("    Your sign-in credential is stored on your GlycemicGPT server, not here.")
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
