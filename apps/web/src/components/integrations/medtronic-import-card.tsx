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
  const [bookmarkletCopied, setBookmarkletCopied] = useState(false);
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

  const copyBookmarklet = useCallback(() => {
    navigator.clipboard?.writeText(bookmarklet).then(
      () => {
        setBookmarkletCopied(true);
        setTimeout(() => setBookmarkletCopied(false), 2000);
      },
      () => {}
    );
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
      <div className="space-y-2 text-sm text-slate-400">
        <p>
          Bring your Medtronic pump history into GlycemicGPT from the CareLink
          website — no pump connection or cables needed.
        </p>
        <p>
          Medtronic doesn&apos;t offer a direct app connection, so you sign in to
          CareLink yourself and send a copy of your data over. There&apos;s a
          quick one-time setup, then importing takes just a few clicks. Your
          CareLink sign-in is used only to fetch the data you ask for, and
          GlycemicGPT never sees your CareLink password or saves your sign-in.
        </p>
      </div>

      {/* Region */}
      <div className="max-w-xs">
        <label
          htmlFor="medtronic-region"
          className="block text-sm font-medium text-slate-300 mb-1"
        >
          Where is your CareLink account?
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
        <p className="mt-1 text-xs text-slate-500">
          Choose the region your Medtronic CareLink account is registered in.
        </p>
      </div>

      {/* Step 1: bookmarklet (one-time setup) */}
      <div className="space-y-2">
        <p className="text-sm font-medium text-slate-300">
          Step 1 — One-time setup: save the GlycemicGPT button
        </p>
        <p className="text-xs text-slate-500">
          Save this button to your browser once. Later, while you&apos;re signed
          in to CareLink, you&apos;ll click it to send your data to GlycemicGPT —
          like a one-click bridge between the two sites. You only do this once.
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <a
            ref={bookmarkletRef}
            href="#"
            onClick={(e) => e.preventDefault()}
            draggable
            title="Drag me to your bookmarks bar"
            className="inline-block cursor-grab rounded-md border border-blue-500/50 bg-blue-500/10 px-3 py-1.5 text-sm font-medium text-blue-300"
          >
            Capture CareLink → GlycemicGPT
          </a>
          <button
            type="button"
            onClick={copyBookmarklet}
            className="rounded-md border border-slate-600 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
          >
            {bookmarkletCopied ? "Copied!" : "Copy button instead"}
          </button>
        </div>

        <div className="space-y-1.5 rounded-md bg-slate-800/50 p-3 text-xs text-slate-400">
          <p className="font-medium text-slate-300">How to save it:</p>
          <p>
            1. Show your browser&apos;s bookmarks bar — the row of saved links
            under the address bar at the top. Press{" "}
            <kbd className="rounded bg-slate-700 px-1">Ctrl</kbd>+
            <kbd className="rounded bg-slate-700 px-1">Shift</kbd>+
            <kbd className="rounded bg-slate-700 px-1">B</kbd> (
            <kbd className="rounded bg-slate-700 px-1">⌘</kbd>+Shift+B on a Mac)
            to show it.
          </p>
          <p>
            2. Drag the blue{" "}
            <span className="text-slate-300">Capture CareLink → GlycemicGPT</span>{" "}
            button up onto that bar.
          </p>
          <p>
            Rather not drag? Click{" "}
            <span className="text-slate-300">“Copy button instead”</span>, then
            right-click your bookmarks bar, choose{" "}
            <span className="text-slate-300">“Add page”</span>, type any name, and
            paste. (Pasting it into the address bar won&apos;t work — browsers
            block that.)
          </p>
        </div>
      </div>

      {/* Step 2: sign in + capture */}
      <div className="space-y-2">
        <p className="text-sm font-medium text-slate-300">
          Step 2 — Sign in to Medtronic CareLink
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
          This opens Medtronic&apos;s CareLink website in a new window. Sign in
          with your Medtronic username and password (you may be asked to confirm
          you&apos;re not a robot). You sign in directly with Medtronic —
          GlycemicGPT never sees your password.
        </p>
        <p className="text-xs text-slate-500">
          Once you&apos;re signed in, click the{" "}
          <span className="text-slate-300">Capture CareLink → GlycemicGPT</span>{" "}
          button you saved (in your bookmarks bar). Your data connection comes
          back here automatically. If nothing appears here after a few seconds,
          the button will have copied a code instead — paste it below:
        </p>
        <div className="flex gap-2">
          <input
            type="text"
            value={pasteValue}
            onChange={(e) => setPasteValue(e.target.value)}
            placeholder="Paste the copied code (only if needed)"
            disabled={isOffline}
            className={inputClass}
          />
          <button
            type="button"
            onClick={usePastedToken}
            disabled={isOffline || !pasteValue.trim()}
            className={clsx(btnClass, "whitespace-nowrap")}
          >
            Use code
          </button>
        </div>
        {token && (
          <p className="text-xs text-green-400">
            ✓ Connected to your CareLink account
            {isFetchingAvail ? " — checking what data is available…" : ""}
          </p>
        )}
      </div>

      {/* Step 3: range + import */}
      {availability && (
        <div className="space-y-3">
          <p className="text-sm font-medium text-slate-300">
            Step 3 — Choose dates and import
          </p>
          <p className="text-xs text-slate-500">
            Your CareLink account has data from{" "}
            {availability.start?.slice(0, 10) ?? "?"} to{" "}
            {availability.end?.slice(0, 10) ?? "?"}. Pick the dates you&apos;d
            like to bring in (up to {MAX_IMPORT_DAYS} days at a time).
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
                ? "The end date needs to be on or after the start date."
                : `That's ${rangeDays} days — please choose ${MAX_IMPORT_DAYS} days or fewer at a time.`}
            </p>
          )}
          <button
            type="button"
            onClick={runImport}
            disabled={isOffline || isImporting || !rangeValid}
            className={btnClass}
          >
            {isImporting ? "Importing…" : "Import these dates"}
          </button>
        </div>
      )}

      {result && (
        <div className="rounded-md border border-green-600/40 bg-green-600/10 p-3 text-sm text-green-300">
          ✓ Done! Imported {result.glucose_stored} glucose readings and{" "}
          {result.events_stored} pump events. You can pick another date range
          above to bring in more.
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
