#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""glooko-capture: a re-runnable Glooko wire-protocol capture helper.

WHY THIS EXISTS
  The Omnipod Cloud Sync via Glooko integration needs the Glooko REST protocol confirmed
  against a real Omnipod-on-Glooko account before the full build. This
  helper logs in the way the real Glooko web app does, then enumerates and captures the
  data endpoints so the protocol can be re-verified in minutes instead of re-discovered.

AUTH -- WHAT THE LIVE SPIKE ACTUALLY FOUND (2026-05-30, against a real account)
  The Discovery hypothesis ("POST /api/v2/users/sign_in with a deviceInformation stub")
  is the MOBILE-app login and it does NOT work for a web-only account: it authenticates
  the credentials (bad creds -> 401) but then returns a detail-less 422 RecordInvalid,
  because the mobile device-registration/consent was never completed. See FINDINGS doc.

  The WORKING path is the web session:
    1. GET  https://us.my.glooko.com/users/sign_in            -> session cookie + CSRF meta
    2. POST https://us.my.glooko.com/users/sign_in?id=login_form  (form-urlencoded:
         authenticity_token, user[email], user[password], commit, language, redirect_to)
       -> 302, sets the authenticated `_logbook-web_session` cookie on domain `.glooko.com`
    3. Replay that cookie on https://us.api.glooko.com/api/v2/* and /api/v3/*.
  Because the cookie's domain is `.glooko.com`, one cookie jar serves both the web host
  (us.my) and the API host (us.api).

  REGION: a US account is served from `us.api.glooko.com` / `us.my.glooko.com` (region-
  PREFIXED), NOT the apex `api.glooko.com` that Discovery assumed.

ENDPOINTS (confirmed live)
  Pump data = `/api/v2/*` keyset-cursor endpoints (require `lastUpdatedAt` + `lastGuid`,
  first page sentinel = the zero-UUID, paginate via the echoed cursor until `lastPage`):
    pumps/scheduled_basals, pumps/normal_boluses, pumps/extended_boluses,
    pumps/events (pod changes live here: type=pod_activating/reservoir_change/...),
    pumps/modes (automatic/manual/limited/hypoprotect), pumps/alarms, insulins, foods,
    exercises, notes, cgm/readings, cgm/egvs.
  CGM glucose = `/api/v3/graph/*` (date-windowed; NOT the v2 cursor -- cgm/egvs was empty
  for this Omnipod-5 account while graph/statistics reported real CGM). Device registry =
  `/api/v3/devices_and_settings`. Data range = `/api/v3/end_dates`.

LICENSE / CLEAN-ROOM
  `nightscout/nightscout-connect` (Glooko driver) and `jpollock/glooko2nightscout-bridge`
  are AGPL-3.0. This is a CLEAN-ROOM reimplementation from the protocol facts captured
  live; no AGPL code is copied. They are credited as prior art that named the endpoint/
  param vocabulary. (AGPL restricts copying code, not learning a wire protocol.)

CREDENTIALS (hard rule)
  Read at runtime from the environment ONLY -- GLOOKO_EMAIL / GLOOKO_PASSWORD (or, for
  --auth cookie, GLOOKO_SESSION_COOKIE). Never an argument default, never written to a
  file, never echoed. Works with `op run`. Email/cookie values are masked in stdout.

PHI
  Raw responses contain the operator's own health data; they are saved only to a
  gitignored local dir (default ./.captures) and NEVER committed. Stdout prints redacted
  shape summaries (field names + types, with timestamp/unit/source samples), not bulk
  values, unless --show-values.

USAGE
  export GLOOKO_EMAIL=...; export GLOOKO_PASSWORD=...     # or: op run --env-file=...
  uv run tools/glooko-capture/capture.py                  # US, web-session login
  uv run tools/glooko-capture/capture.py --max-pages 3    # walk a few cursor pages
  GLOOKO_SESSION_COOKIE=... uv run tools/glooko-capture/capture.py --auth cookie
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Region -> (web host, api host). US/EU are region-PREFIXED (live finding); the apex
# api.glooko.com is NOT the per-account host. EU is untested here (US account) and is
# known-fragile (nightscout-connect issue #14).
HOSTS = {
    "US": {"web": "https://us.my.glooko.com", "api": "https://us.api.glooko.com"},
    "EU": {"web": "https://eu.my.glooko.com", "api": "https://eu.api.glooko.com"},
}

SIGN_IN_PAGE = "/users/sign_in"
SIGN_IN_POST = "/users/sign_in?id=login_form"
SESSION_USERS = "/api/v3/session/users"

# Keyset-cursor first-page sentinel. The literal "0" yields a 500; the zero-UUID is the
# accepted first-page value, and the response echoes the next page's lastUpdatedAt/lastGuid.
ZERO_GUID = "00000000-0000-0000-0000-000000000000"
EPOCH_CURSOR = "2015-01-01T00:00:00.000Z"  # well before any Glooko data; walks full history

# v2 keyset-cursor endpoints: (path, response array key). Confirmed to exist live; absent
# routes (e.g. pumps/temp_basals, pod_activations) 404 and are intentionally not listed.
CURSOR_ENDPOINTS = [
    ("/api/v2/cgm/readings", "readings"),
    ("/api/v2/cgm/egvs", "egvs"),
    ("/api/v2/pumps/scheduled_basals", "scheduledBasals"),
    ("/api/v2/pumps/normal_boluses", "normalBoluses"),
    ("/api/v2/pumps/extended_boluses", "extendedBoluses"),
    ("/api/v2/pumps/events", "events"),  # pod changes, suspends, primes
    ("/api/v2/pumps/modes", "modes"),  # automode/manual/limited
    ("/api/v2/pumps/alarms", "alarms"),
    ("/api/v2/insulins", "insulins"),
    ("/api/v2/foods", "foods"),
    ("/api/v2/exercises", "exercises"),
    ("/api/v2/notes", "notes"),
]


def mask(value: str | None, keep: int = 2) -> str:
    if not value:
        return "<empty>"
    if len(value) <= keep * 2:
        return value[0] + "***"
    return f"{value[:keep]}***{value[-keep:]} (len={len(value)})"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else mask(email)


def typeof(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return f"list[{typeof(value[0]) if value else '?'}]"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


# Field-name heuristics for the normalization facts (AC2d / AC4).
SOURCE_HINTS = ("pumpname", "pumpguid", "source", "devicemodel", "brand", "manufacturer", "referencedevice")
TIME_HINTS = ("timestamp", "time", "date", "offset", "utc")
ID_HINTS = ("guid", "serial", "_id", "userid", "patientid")


def is_id(key: str) -> bool:
    kl = key.lower()
    return any(h in kl for h in ID_HINTS) or kl == "id"


def summarize(records: list, show_values: bool) -> dict[str, Any]:
    if not isinstance(records, list):
        return {"count": "not-a-list"}
    if not records:
        return {"count": 0}
    first = records[0]
    if not isinstance(first, dict):
        return {"count": len(records), "scalar": typeof(first)}
    fields = {k: typeof(v) for k, v in first.items()}
    source_fields = [k for k in fields if any(h in k.lower() for h in SOURCE_HINTS)]
    time_fields = [k for k in fields if any(h in k.lower() for h in TIME_HINTS)]
    summary: dict[str, Any] = {
        "count": len(records),
        "fields": fields,
        "source_fields": source_fields,  # AC2d
        "time_fields": time_fields,  # AC4
    }
    # First/last record timestamps -> proves how far back the data reaches (AC2c).
    ts_key = next((k for k in ("pumpTimestamp", "timestamp", "timestampUtc") if k in first), None)
    if ts_key:
        summary["first_ts"] = first.get(ts_key)
        summary["last_ts"] = records[-1].get(ts_key) if isinstance(records[-1], dict) else None
    # Distinct source/type values across the batch (vendor mixing + event vocab).
    for sf in source_fields + (["type"] if "type" in fields else []):
        distinct = sorted({str(r.get(sf)) for r in records if isinstance(r, dict)})[:12]
        summary.setdefault("distinct_values", {})[sf] = distinct
    # Non-id sample: keep timestamp/source/unit values; mask identifiers; show the rest
    # only with --show-values (PHI).
    sample = {}
    for k, v in first.items():
        if is_id(k):
            sample[k] = f"<{typeof(v)}>"
        elif show_values or k in time_fields or k in source_fields or "unit" in k.lower():
            sample[k] = v
    summary["sample_record"] = sample
    return summary


class GlookoCapture:
    def __init__(self, region: str, out_dir: Path, show_values: bool):
        self.region = region
        self.web = HOSTS[region]["web"]
        self.api = HOSTS[region]["api"]
        # No base_url: we hit two hosts that share the `.glooko.com` cookie jar.
        self.client = httpx.Client(
            timeout=40.0,
            follow_redirects=True,
            headers={"User-Agent": "GlycemicGPT-glooko-capture/0.2 (spike)"},
        )
        self.out_dir = out_dir
        self.show_values = show_values
        self.patient: str | None = None
        self.results: dict[str, Any] = {"region": region, "web": self.web, "api": self.api, "endpoints": {}}

    def close(self) -> None:
        self.client.close()

    def _save(self, name: str, payload: Any) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / f"{name}.json").write_text(json.dumps(payload, indent=2, default=str))

    # ---- AC1: auth (the WORKING web-session path) -----------------------------
    def web_login(self, email: str, password: str) -> bool:
        print(f"[auth] GET {self.web}{SIGN_IN_PAGE}  (fetch CSRF + session cookie)")
        page = self.client.get(self.web + SIGN_IN_PAGE)
        if page.status_code >= 400:
            print(f"[auth] sign-in page returned {page.status_code}")
            return False
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text)
        token = m.group(1) if m else ""
        if not token:
            print("[auth] WARNING: no csrf-token meta found; proceeding without (login may fail).")
        form = {
            "authenticity_token": token,
            "user[email]": email,
            "user[password]": password,
            "commit": "Log In",
            "language": "en",
            "redirect_to": "",
        }
        print(f"[auth] POST {self.web}{SIGN_IN_POST}  (email={mask_email(email)})")
        resp = self.client.post(
            self.web + SIGN_IN_POST,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": self.web},
        )
        cookie_names = [c.name for c in self.client.cookies.jar]
        print(f"[auth] status={resp.status_code}; cookies now: {cookie_names}")
        ok = "_logbook-web_session" in cookie_names
        self.results["auth"] = {"status": resp.status_code, "cookies": cookie_names, "csrf_found": bool(token)}
        if not ok:
            print("[auth] FAILED: no _logbook-web_session cookie -> credentials or CSRF rejected.")
        return ok

    def cookie_login(self, cookie_value: str) -> bool:
        # Fallback: replay a _logbook-web_session value copied from a logged-in browser.
        self.client.cookies.set("_logbook-web_session", cookie_value, domain="glooko.com", path="/")
        print(f"[auth] using supplied session cookie {mask(cookie_value)}")
        self.results["auth"] = {"mode": "cookie"}
        return True

    def verify_session(self) -> bool:
        r = self.client.get(self.api + SESSION_USERS, headers={"Accept": "application/json"})
        print(f"[auth] GET {SESSION_USERS} -> {r.status_code}")
        if r.status_code != 200:
            return False
        try:
            body = r.json()
        except Exception:
            return False
        self._save("00_session_users", body)
        self.patient = self._find_patient(body)
        print(f"[auth] patient slug = {mask(self.patient) if self.patient else 'NOT FOUND'}")
        self.results["auth"]["patient_found"] = bool(self.patient)
        return True

    @staticmethod
    def _find_patient(body: Any, _depth: int = 0) -> str | None:
        # The data endpoints key on a human-readable patient slug (e.g. "adjective-name-1234").
        # Find it under any *glookoCode*/*patient* key in the session payload.
        if _depth > 6:
            return None
        if isinstance(body, dict):
            for k, v in body.items():
                if isinstance(v, str) and ("glookocode" in k.lower() or k.lower() == "patient"):
                    return v
            for v in body.values():
                hit = GlookoCapture._find_patient(v, _depth + 1)
                if hit:
                    return hit
        elif isinstance(body, list):
            for v in body:
                hit = GlookoCapture._find_patient(v, _depth + 1)
                if hit:
                    return hit
        return None

    # ---- helpers --------------------------------------------------------------
    def api_get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        return self.client.get(self.api + path, params=params, headers={"Accept": "application/json"})

    # ---- AC2c/AC4: data range + device registry -------------------------------
    def fetch_range_and_devices(self) -> None:
        if not self.patient:
            return
        end = self.api_get("/api/v3/end_dates", {"patient": self.patient})
        if end.status_code == 200:
            body = end.json()
            self._save("01_end_dates", body)
            self.results["end_dates"] = body
            print(f"[range] /api/v3/end_dates -> {body}")
        dev = self.api_get("/api/v3/devices_and_settings", {"patient": self.patient})
        if dev.status_code == 200:
            body = dev.json()
            self._save("02_devices_and_settings", body)
            # Note the duplicate top-level `devices` key footgun: httpx/json keeps the last.
            devs = body.get("devices", []) if isinstance(body, dict) else []
            inv = [
                {"brand": d.get("brand"), "model": d.get("model"),
                 "referenceDeviceId": d.get("referenceDeviceId") or d.get("reference_device_id"),
                 "type": d.get("type")}
                for d in devs if isinstance(d, dict)
            ]
            self.results["devices"] = inv
            print(f"[devices] {len(inv)} device(s): {inv}")

    # ---- AC2/AC2b/AC2c/AC4: cursor enumeration --------------------------------
    def probe_cursor(self, path: str, arr_key: str, max_pages: int) -> dict[str, Any]:
        if not self.patient:
            return {"skipped": "no patient slug"}
        last_updated, last_guid = EPOCH_CURSOR, ZERO_GUID
        all_records: list = []
        pages = 0
        record = {"path": path, "array_key": arr_key}
        while pages < max_pages:
            params = {
                "patient": self.patient,
                "lastUpdatedAt": last_updated,
                "lastGuid": last_guid,
                "limit": 500,
            }
            resp = self.api_get(path, params)
            if resp.status_code != 200:
                record["status"] = resp.status_code
                record["body"] = resp.text[:160]
                break
            body = resp.json()
            recs = body.get(arr_key, []) if isinstance(body, dict) else (body if isinstance(body, list) else [])
            all_records.extend(recs)
            pages += 1
            last_page = bool(body.get("lastPage")) if isinstance(body, dict) else True
            last_updated = body.get("lastUpdatedAt", last_updated) if isinstance(body, dict) else last_updated
            last_guid = body.get("lastGuid", last_guid) if isinstance(body, dict) else last_guid
            if last_page or not recs:
                break
            time.sleep(0.3)
        record["status"] = record.get("status", 200)
        record["pages_fetched"] = pages
        record["total_records"] = len(all_records)
        if all_records:
            self._save(f"ep_{path.strip('/').replace('/', '_')}", all_records[:1000])
            record["summary"] = summarize(all_records, self.show_values)
        return record

    def run_enumeration(self, max_pages: int) -> None:
        print(f"\n[probe] keyset-cursor enumeration from epoch (max_pages={max_pages}, patient={mask(self.patient)})")
        for path, arr_key in CURSOR_ENDPOINTS:
            rec = self.probe_cursor(path, arr_key, max_pages)
            self.results["endpoints"][path] = rec
            n = rec.get("total_records", 0)
            summ = rec.get("summary", {})
            tag = f"OK n={n}" if rec.get("status") == 200 else f"status={rec.get('status')}"
            line = f"  {path:36s} {tag}"
            if summ.get("first_ts"):
                line += f"  span {summ['first_ts']} .. {summ['last_ts']}"
            print(line)
            if summ.get("distinct_values"):
                for k, vals in summ["distinct_values"].items():
                    print(f"        {k} values: {vals}")
            time.sleep(0.3)

    # ---- glucose presence (v3 graph) -----------------------------------------
    def fetch_glucose_stats(self) -> None:
        if not self.patient:
            return
        end = (self.results.get("end_dates") or {}).get("endDateReport") or _today_iso()
        params = {
            "patient": self.patient,
            "startDate": "2015-01-01T00:00:00.000Z",
            "endDate": end,
            "egv": "true",
            "includeInsulin": "true",
        }
        r = self.api_get("/api/v3/graph/statistics/overall", params)
        if r.status_code == 200:
            body = r.json()
            self._save("03_graph_statistics_overall", body)
            keys = ("averageBg", "median", "min", "max", "readingsPerDay", "inRangePercentage",
                    "gmi", "activeCgmTimePercentage", "totalInsulinPerDay")
            glucose = {k: body.get(k) for k in keys if k in body}
            self.results["glucose_stats"] = glucose
            print(f"[glucose] /api/v3/graph/statistics/overall (egv=true) -> {glucose}")
            print("[glucose] (units inferred from min/max range: mg/dL if ~40-400, mmol/L if ~2-22)")


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT23:59:59.999Z")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="glooko-capture",
                                description="Capture the Glooko wire protocol against a real account.")
    p.add_argument("--region", choices=["US", "EU"], default="US")
    p.add_argument("--auth", choices=["web", "cookie"], default="web",
                   help="web = Devise form login (default); cookie = replay GLOOKO_SESSION_COOKIE")
    p.add_argument("--max-pages", type=int, default=1,
                   help="cursor pages per endpoint (1 = shape only; raise to walk history)")
    p.add_argument("--out", default=str(Path(__file__).parent / ".captures"),
                   help="raw-dump dir (gitignored, PHI)")
    p.add_argument("--show-values", action="store_true", help="include full record values in output (PHI)")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out).resolve()
    # PHI containment: only paths under this tool dir are covered by the local
    # .gitignore. Warn loudly if captures would land somewhere that could be tracked.
    tool_dir = Path(__file__).resolve().parent
    if tool_dir not in out_dir.parents and out_dir != tool_dir:
        print(
            f"WARNING: --out {out_dir} is OUTSIDE {tool_dir} -- it is NOT covered by the "
            f"tool's .gitignore. Raw captures contain PHI; ensure this path is gitignored.",
            file=sys.stderr,
        )
    cap = GlookoCapture(args.region, out_dir, args.show_values)
    print(f"glooko-capture  region={args.region}  auth={args.auth}  out={out_dir}")
    print("LICENSE: clean-room; prior art = nightscout-connect + jpollock/glooko2nightscout-bridge (AGPL-3.0, studied not copied).")
    try:
        if args.auth == "cookie":
            cookie = os.environ.get("GLOOKO_SESSION_COOKIE")
            if not cookie:
                print("error: set GLOOKO_SESSION_COOKIE for --auth cookie.", file=sys.stderr)
                return 2
            cap.cookie_login(cookie)
        else:
            email, password = os.environ.get("GLOOKO_EMAIL"), os.environ.get("GLOOKO_PASSWORD")
            if not email or not password:
                print("error: set GLOOKO_EMAIL and GLOOKO_PASSWORD in the environment (never on the CLI).", file=sys.stderr)
                return 2
            if not cap.web_login(email, password):
                cap._save("_results", cap.results)
                return 1
        if not cap.verify_session():
            print("[done] session not valid -- cannot enumerate.")
            cap._save("_results", cap.results)
            return 1
        cap.fetch_range_and_devices()
        cap.run_enumeration(args.max_pages)
        cap.fetch_glucose_stats()
    finally:
        cap._save("_results", cap.results)
        cap.close()
    print(f"\n[done] raw captures + _results.json under {args.out} (gitignored, PHI -- do not commit).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
