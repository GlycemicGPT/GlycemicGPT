"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import {
  getMedtronicAvailability,
  importMedtronicRange,
  type MedtronicAvailabilityResponse,
  type MedtronicImportResponse,
} from "@/lib/api";

/**
 * Medtronic CareLink manual historical import.
 *
 * CareLink has no API and no durable server-side session, so we can't pull
 * autonomously like Tandem. Instead: the user logs into CareLink in a popup
 * (solving the captcha) and clicks a one-time GlycemicGPT bookmarklet that
 * reads the short-lived auth_tmp_token and hands it back via postMessage (or
 * clipboard fallback). We then validate it, show the available range, and let
 * the user import a chosen window. The token is used for the import only and
 * is never stored.
 */

const MAX_IMPORT_DAYS = 31;

const REGIONS = [
  {
    code: "US",
    label: "United States",
    loginUrl: "https://carelink.minimed.com/",
    origin: "https://carelink.minimed.com",
  },
  {
    code: "EU",
    label: "Europe / International",
    loginUrl: "https://carelink.minimed.eu/",
    origin: "https://carelink.minimed.eu",
  },
] as const;

const MESSAGE_SOURCE = "glycemicgpt-carelink";

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function daysBetween(a: string, b: string): number {
  return Math.round(
    (new Date(b).getTime() - new Date(a).getTime()) / 86_400_000
  );
}

export function MedtronicImportCard({ isOffline }: { isOffline: boolean }) {
  const [regionCode, setRegionCode] = useState<string>("US");
  const [token, setToken] = useState<string>("");
  const [pasteValue, setPasteValue] = useState<string>("");
  const [availability, setAvailability] =
    useState<MedtronicAvailabilityResponse | null>(null);
  const [importStart, setImportStart] = useState<string>("");
  const [importEnd, setImportEnd] = useState<string>("");
  const [isFetchingAvail, setIsFetchingAvail] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MedtronicImportResponse | null>(null);

  const region = useMemo(
    () => REGIONS.find((r) => r.code === regionCode) ?? REGIONS[0],
    [regionCode]
  );
  const browserTz = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    []
  );

  const bookmarklet = useMemo(() => {
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    // Reads the non-httpOnly auth_tmp_token, posts it to the opener (this app),
    // and falls back to copying it to the clipboard if the opener is gone.
    return `javascript:(function(){try{var m=document.cookie.match(/(?:^|;\\s*)auth_tmp_token=([^;]+)/);if(!m){alert('GlycemicGPT: no CareLink token found - are you signed in?');return;}var t=decodeURIComponent(m[1]);if(window.opener&&!window.opener.closed){window.opener.postMessage({source:'${MESSAGE_SOURCE}',token:t},'${origin}');alert('GlycemicGPT: token sent. You can close this tab.');}else if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(function(){alert('GlycemicGPT: token copied. Paste it into GlycemicGPT.');},function(){prompt('GlycemicGPT: copy this token:',t);});}else{prompt('GlycemicGPT: copy this token:',t);}}catch(e){alert('GlycemicGPT capture error: '+e);}})();`;
  }, []);

  const bookmarkletRef = useRef<HTMLAnchorElement | null>(null);
  useEffect(() => {
    // Set the javascript: href via the DOM so React doesn't strip it; the user
    // drags this to their bookmarks bar (clicking it here is a no-op).
    if (bookmarkletRef.current) {
      bookmarkletRef.current.setAttribute("href", bookmarklet);
    }
  }, [bookmarklet]);

  const fetchAvailability = useCallback(
    async (tok: string) => {
      setError(null);
      setResult(null);
      setIsFetchingAvail(true);
      try {
        const avail = await getMedtronicAvailability(region.code, tok);
        setAvailability(avail);
        // Default the picker to the most recent ~14 days of available data.
        if (avail.end) {
          const end = avail.end.slice(0, 10);
          const earliest = avail.start ? avail.start.slice(0, 10) : end;
          const proposedStart = isoDate(
            new Date(new Date(end).getTime() - 14 * 86_400_000)
          );
          setImportEnd(end);
          setImportStart(proposedStart < earliest ? earliest : proposedStart);
        }
      } catch (e) {
        setAvailability(null);
        setError(e instanceof Error ? e.message : "Failed to read availability");
      } finally {
        setIsFetchingAvail(false);
      }
    },
    [region.code]
  );

  // Listen for the bookmarklet's postMessage from the CareLink popup.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.origin !== region.origin) return;
      const data = event.data;
      if (
        data &&
        data.source === MESSAGE_SOURCE &&
        typeof data.token === "string" &&
        data.token.length > 0
      ) {
        setToken(data.token);
        void fetchAvailability(data.token);
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [region.origin, fetchAvailability]);

  const openCareLink = useCallback(() => {
    setError(null);
    window.open(region.loginUrl, "carelink_login", "width=1100,height=860");
  }, [region.loginUrl]);

  const usePastedToken = useCallback(() => {
    const t = pasteValue.trim();
    if (!t) return;
    setToken(t);
    void fetchAvailability(t);
  }, [pasteValue, fetchAvailability]);

  const rangeDays =
    importStart && importEnd ? daysBetween(importStart, importEnd) : 0;
  const rangeValid =
    !!importStart &&
    !!importEnd &&
    rangeDays >= 0 &&
    rangeDays <= MAX_IMPORT_DAYS;

  const runImport = useCallback(async () => {
    if (!token || !rangeValid) return;
    setError(null);
    setResult(null);
    setIsImporting(true);
    try {
      const res = await importMedtronicRange(
        region.code,
        token,
        importStart,
        importEnd,
        browserTz
      );
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setIsImporting(false);
    }
  }, [token, rangeValid, region.code, importStart, importEnd, browserTz]);

  const inputClass = clsx(
    "w-full rounded-lg border px-3 py-2 text-sm",
    "bg-slate-800 border-slate-700 text-slate-200 placeholder:text-slate-500",
    "focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent",
    "disabled:opacity-50 disabled:cursor-not-allowed"
  );
  const btnClass = clsx(
    "rounded-lg px-4 py-2 text-sm font-medium transition-colors",
    "bg-blue-600 hover:bg-blue-500 text-white",
    "disabled:opacity-50 disabled:cursor-not-allowed"
  );

  return (
    <div className="space-y-5 rounded-lg border border-slate-700 bg-slate-900/40 p-4">
      <p className="text-sm text-slate-400">
        CareLink has no public API, so importing is manual: sign in to CareLink
        (one-time captcha), click the GlycemicGPT bookmarklet to hand your
        session back, then pick a date range to import. Your session token is
        used only for the import and is never stored.
      </p>

      {/* Region */}
      <div className="max-w-xs">
        <label
          htmlFor="medtronic-region"
          className="block text-sm font-medium text-slate-300 mb-1"
        >
          Region
        </label>
        <select
          id="medtronic-region"
          value={regionCode}
          onChange={(e) => {
            setRegionCode(e.target.value);
            setToken("");
            setAvailability(null);
          }}
          disabled={isOffline}
          className={inputClass}
        >
          {REGIONS.map((r) => (
            <option key={r.code} value={r.code}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      {/* Step 1: bookmarklet (one-time setup) */}
      <div className="space-y-2">
        <p className="text-sm font-medium text-slate-300">
          1. Save the capture bookmarklet (one time)
        </p>
        <p className="text-xs text-slate-500">
          Drag this button to your bookmarks bar:
        </p>
        <a
          ref={bookmarkletRef}
          href="#"
          onClick={(e) => e.preventDefault()}
          draggable
          className="inline-block cursor-grab rounded-md border border-blue-500/50 bg-blue-500/10 px-3 py-1.5 text-sm font-medium text-blue-300"
        >
          Capture CareLink → GlycemicGPT
        </a>
      </div>

      {/* Step 2: sign in + capture */}
      <div className="space-y-2">
        <p className="text-sm font-medium text-slate-300">
          2. Sign in to CareLink and capture
        </p>
        <button
          type="button"
          onClick={openCareLink}
          disabled={isOffline}
          className={btnClass}
        >
          Open CareLink &amp; sign in
        </button>
        <p className="text-xs text-slate-500">
          After signing in, click the bookmarklet on the CareLink page. If the
          token doesn&apos;t arrive automatically, the bookmarklet copies it —
          paste it here:
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={pasteValue}
            onChange={(e) => setPasteValue(e.target.value)}
            placeholder="Paste captured token (fallback)"
            disabled={isOffline}
            className={inputClass}
          />
          <button
            type="button"
            onClick={usePastedToken}
            disabled={isOffline || !pasteValue.trim()}
            className={clsx(btnClass, "whitespace-nowrap")}
          >
            Use token
          </button>
        </div>
        {token && (
          <p className="text-xs text-green-400">
            ✓ Session captured{isFetchingAvail ? " — reading availability…" : ""}
          </p>
        )}
      </div>

      {/* Step 3: range + import */}
      {availability && (
        <div className="space-y-3">
          <p className="text-sm font-medium text-slate-300">
            3. Choose a range to import
          </p>
          <p className="text-xs text-slate-500">
            Data available {availability.start?.slice(0, 10) ?? "?"} →{" "}
            {availability.end?.slice(0, 10) ?? "?"}. Max {MAX_IMPORT_DAYS} days
            per import.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-w-md">
            <div>
              <label
                htmlFor="medtronic-start"
                className="block text-xs text-slate-400 mb-1"
              >
                Start
              </label>
              <input
                id="medtronic-start"
                type="date"
                value={importStart}
                min={availability.start?.slice(0, 10)}
                max={availability.end?.slice(0, 10)}
                onChange={(e) => setImportStart(e.target.value)}
                disabled={isImporting}
                className={inputClass}
              />
            </div>
            <div>
              <label
                htmlFor="medtronic-end"
                className="block text-xs text-slate-400 mb-1"
              >
                End
              </label>
              <input
                id="medtronic-end"
                type="date"
                value={importEnd}
                min={availability.start?.slice(0, 10)}
                max={availability.end?.slice(0, 10)}
                onChange={(e) => setImportEnd(e.target.value)}
                disabled={isImporting}
                className={inputClass}
              />
            </div>
          </div>
          {importStart && importEnd && !rangeValid && (
            <p className="text-xs text-amber-400">
              {rangeDays < 0
                ? "End date must be on or after the start date."
                : `Range is ${rangeDays} days — max ${MAX_IMPORT_DAYS} per import.`}
            </p>
          )}
          <button
            type="button"
            onClick={runImport}
            disabled={isOffline || isImporting || !rangeValid}
            className={btnClass}
          >
            {isImporting ? "Importing…" : "Import range"}
          </button>
        </div>
      )}

      {result && (
        <div className="rounded-md border border-green-600/40 bg-green-600/10 p-3 text-sm text-green-300">
          Imported {result.glucose_stored} glucose readings and{" "}
          {result.events_stored} pump events.
        </div>
      )}
      {error && (
        <div className="rounded-md border border-red-600/40 bg-red-600/10 p-3 text-sm text-red-300">
          {error}
        </div>
      )}
    </div>
  );
}
