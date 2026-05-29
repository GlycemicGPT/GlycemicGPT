# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27", "playwright>=1.40"]
# ///
"""GlycemicGPT Medtronic CareLink CarePartner (Connect) — local login helper.

WHY THIS EXISTS
---------------
Medtronic's CarePartner login can only be done interactively in a browser, and
on success it redirects to a mobile-app URL scheme (``com.medtronic.carepartner:``)
that a server can't receive and a desktop browser can't open. So this one-time
local helper drives the login in a real browser, lets you solve the reCAPTCHA,
and intercepts that redirect's authorization ``code`` at the network layer
(the same technique the community carelink-python-client uses). It then hands
the code to YOUR GlycemicGPT backend, which exchanges it for the long-lived
credential and stores it server-side.

WHAT IT NEVER SEES
------------------
- Your CareLink password (you type that directly into Medtronic's page).
- Your GlycemicGPT password (you authenticate with a short-lived *pairing
  token* you copy from the GlycemicGPT web UI).
- The Medtronic refresh token (the backend does the code→token exchange; the
  token is created and stored on your server and never touches this machine).

USAGE
-----
1. In GlycemicGPT → Settings → Integrations → Cloud Sync → Medtronic CareLink,
   click "Connect with the desktop helper" and copy the pairing token.
2. One-time browser install:  ``playwright install chromium``
3. Run (from the repo root):
     uv run tools/medtronic-connect-login/medtronic_connect_login.py \
        --api https://your-glycemicgpt-instance \
        --pair <PAIRING_TOKEN> \
        --username <YOUR_CARELINK_USERNAME>
4. A browser opens. Sign in to CareLink and solve the captcha. When it
   succeeds the helper captures the code, finishes on the server, and prints
   "Connected". You can close the browser.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx

AUTHORIZE_PATH = "/api/integrations/medtronic/connect/authorize-url"
EXCHANGE_PATH = "/api/integrations/medtronic/connect/exchange"
PAIR_TOKEN_HEADER = "X-Connect-Pair-Token"

#: The mobile-app redirect scheme whose 302 carries the authorization code.
_REDIRECT_SCHEME = "com.medtronic.carepartner:"
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


# --- pure helpers (unit-testable; no network/browser) ---


def build_url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def is_capture_redirect(status: int, location: str | None) -> bool:
    """True if this response is the CarePartner redirect carrying the code."""
    return (
        status in _REDIRECT_STATUSES
        and bool(location)
        and location.startswith(_REDIRECT_SCHEME)
        and "code=" in location
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="medtronic_connect_login",
        description="One-time local login helper for GlycemicGPT Medtronic Connect.",
    )
    p.add_argument("--api", required=True, help="Your GlycemicGPT base URL")
    p.add_argument(
        "--pair", required=True, help="Pairing token copied from the GlycemicGPT UI"
    )
    p.add_argument("--username", required=True, help="Your CareLink username")
    p.add_argument(
        "--region",
        default="US",
        help="CarePartner region: US, or EU for non-US (UK/EU/AU/ZA/…)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for you to complete the browser login (default 300)",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser headless (NOT recommended — you must solve a captcha)",
    )
    return p.parse_args(argv)


# --- network + browser steps ---


async def _get_authorize_url(args: argparse.Namespace) -> dict:
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(
            build_url(args.api, AUTHORIZE_PATH),
            params={"region": args.region},
            headers={PAIR_TOKEN_HEADER: args.pair},
        )
    if resp.status_code == 401:
        raise SystemExit(
            "Pairing token rejected or expired. Reissue it from the GlycemicGPT UI "
            "and run this again."
        )
    if resp.status_code >= 400:
        raise SystemExit(f"Could not start login ({resp.status_code}): {resp.text}")
    return resp.json()


async def _capture_redirect(authorize_url: str, timeout: int, headless: bool) -> str:
    """Open the browser, let the user log in, return the captured redirect URL."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise SystemExit(
            "Playwright is required. Install it with:\n"
            "  pip install playwright && playwright install chromium\n"
            "(or run this script with `uv run`, then `playwright install chromium`)."
        ) from e

    loop = asyncio.get_event_loop()
    captured: asyncio.Future[str] = loop.create_future()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        def on_response(resp) -> None:
            if captured.done():
                return
            if is_capture_redirect(resp.status, resp.headers.get("location")):
                captured.set_result(resp.headers["location"])

        page.on("response", on_response)
        print("\nA browser window is opening. Sign in to CareLink and solve the")
        print("captcha. Do NOT close the window — it closes itself when done.\n")
        try:
            await page.goto(authorize_url, wait_until="domcontentloaded")
        except Exception as e:
            # Surface a real failure to open the login page (bad --api, network,
            # etc.) immediately rather than hiding it behind a later "timeout".
            # The post-login custom-scheme redirect is a SEPARATE navigation, not
            # this initial goto, so it won't be caught here.
            await browser.close()
            raise SystemExit(f"Could not open the CareLink login page: {e}") from e
        try:
            redirect_url = await asyncio.wait_for(captured, timeout=timeout)
        except TimeoutError as e:
            raise SystemExit(
                "Timed out waiting for sign-in. Run again and complete the login "
                "more quickly (the code is short-lived)."
            ) from e
        finally:
            await browser.close()
    return redirect_url


async def _exchange(
    args: argparse.Namespace, pkce_session: str, redirect_url: str
) -> dict:
    # v1 (patient-self) payload: connecting the user's OWN Medtronic account.
    # The follower / care-partner case needs role + patient_id too (the backend
    # /exchange accepts them); that's a tracked follow-up, not in v1. See README.
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            build_url(args.api, EXCHANGE_PATH),
            headers={PAIR_TOKEN_HEADER: args.pair},
            json={
                "pkce_session": pkce_session,
                "redirect_url": redirect_url,
                "username": args.username,
            },
        )
    if resp.status_code == 401:
        raise SystemExit(
            "The CareLink login could not be completed (the code may have expired). "
            "Run this again and paste/sign in promptly."
        )
    if resp.status_code >= 400:
        raise SystemExit(f"Connect failed ({resp.status_code}): {resp.text}")
    return resp.json()


async def run_login(args: argparse.Namespace) -> int:
    start = await _get_authorize_url(args)
    redirect_url = await _capture_redirect(
        start["authorize_url"], timeout=args.timeout, headless=args.headless
    )
    status = await _exchange(args, start["pkce_session"], redirect_url)
    print("\n✓ Connected. GlycemicGPT will now sync your Medtronic data automatically.")
    print(f"  status={status.get('status')} region={status.get('region')}")
    print("  Your sign-in credential is stored on your GlycemicGPT server, not here.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return asyncio.run(run_login(args))


if __name__ == "__main__":
    raise SystemExit(main())
