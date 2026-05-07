"""Synthetic Nightscout uploader.

Continuously POSTs CGM entries to a local Nightscout instance so the
GlycemicGPT scheduler / dashboard can be visually verified against
"new data arriving in real time" instead of static fixture data.

NOT shipped in any production image. Lives in the repo so the script
itself is reviewable + version-controlled, but it never enters a
Dockerfile context.

Usage:
    # Default: post every 60 seconds to http://127.0.0.1:1337
    python3 dev/ns_synthetic_uploader.py

    # Faster cadence for active iteration
    NS_CADENCE_SECONDS=10 python3 dev/ns_synthetic_uploader.py

    # Different baseline / volatility
    NS_BASELINE_MGDL=140 NS_VOLATILITY=8 python3 dev/ns_synthetic_uploader.py

Environment:
    NS_BASE_URL          base URL of the Nightscout instance
                          (default http://127.0.0.1:1337)
    NS_API_SECRET        REQUIRED. Plaintext API_SECRET for the
                          target instance; gets SHA-1 hashed in the
                          api-secret header. Whatever you set as the
                          `API_SECRET` env on the NS container.
    NS_CADENCE_SECONDS   seconds between entries
                          (default 60)
    NS_BASELINE_MGDL     mean of the random walk
                          (default 120)
    NS_VOLATILITY        per-step jitter in mg/dL
                          (default 5)
    NS_DEVICE_NAME       value for the `device` field
                          (default glycemicgpt-synthetic-uploader)

Stops on Ctrl-C. Doesn't backfill -- only posts forward in time
starting from `now()`.

Requires only the stdlib + a Python 3.11+ interpreter (no httpx /
requests). Curl-equivalent over urllib so the script can run from
any environment that has Python.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import random
import signal
import socket
import sys
import time
import urllib.error
import urllib.request


def _hash_secret(secret: str) -> str:
    return hashlib.sha1(secret.encode("utf-8")).hexdigest()


def _direction_for(prev: int, curr: int) -> str:
    """Map mg/dL delta to Nightscout's trend-arrow vocabulary.

    Nightscout uses the Dexcom direction strings:
      DoubleUp / SingleUp / FortyFiveUp / Flat
      / FortyFiveDown / SingleDown / DoubleDown
    Roughly: each step is 5 minutes, so a "rate" in mg/dL/min is
    `delta / cadence_minutes`.
    """
    delta = curr - prev
    if delta >= 15:
        return "DoubleUp"
    if delta >= 7:
        return "SingleUp"
    if delta >= 3:
        return "FortyFiveUp"
    if delta <= -15:
        return "DoubleDown"
    if delta <= -7:
        return "SingleDown"
    if delta <= -3:
        return "FortyFiveDown"
    return "Flat"


def _post_entry(
    base_url: str,
    secret_hash: str,
    sgv: int,
    direction: str,
    device: str,
) -> None:
    """POST one entry to /api/v1/entries.json.

    Raises urllib.error.HTTPError on non-2xx; caller prints + continues.
    """
    now = datetime.datetime.now(datetime.UTC)
    payload = [
        {
            "type": "sgv",
            "sgv": sgv,
            "direction": direction,
            "date": int(now.timestamp() * 1000),
            "dateString": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "device": device,
        }
    ]
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/entries.json",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "api-secret": secret_hash,
        },
        method="POST",
    )
    # urlopen raises HTTPError for any non-2xx (the default
    # HTTPErrorProcessor handles that for us); reaching the body of
    # this `with` means we got a 2xx. Don't manually guard against
    # specific 2xx codes -- treating 202/204 as errors would be wrong.
    with urllib.request.urlopen(req, timeout=10):
        pass


def main() -> int:
    base_url = os.environ.get("NS_BASE_URL", "http://127.0.0.1:1337")
    # Required: don't bake in a default secret value, even for a
    # dev-only test stack. Forcing the operator to set it explicitly
    # keeps a stray credential out of the repo and surfaces
    # misconfiguration immediately rather than silently uploading
    # to whatever instance happens to share the default secret.
    secret = os.environ.get("NS_API_SECRET")
    if not secret:
        print(
            "ERROR: NS_API_SECRET environment variable is required.\n"
            "Set it to the plaintext API_SECRET of your target "
            "Nightscout instance. See dev/README.md for usage.",
            file=sys.stderr,
        )
        return 2
    cadence = float(os.environ.get("NS_CADENCE_SECONDS", "60"))
    baseline = float(os.environ.get("NS_BASELINE_MGDL", "120"))
    volatility = float(os.environ.get("NS_VOLATILITY", "5"))
    device = os.environ.get("NS_DEVICE_NAME", "glycemicgpt-synthetic-uploader")

    # Mean-reverting random walk with diurnal sine bias so the curve
    # doesn't drift to one side. Bias adds +/- ~25 mg/dL over a 24h
    # cycle so the dashboard doesn't render a flat line.
    secret_hash = _hash_secret(secret)
    sgv = max(40, min(400, int(baseline)))
    prev_sgv = sgv
    started_at = time.monotonic()

    print(
        f"[uploader] posting to {base_url} every {cadence}s "
        f"(baseline {baseline}, volatility {volatility})",
        flush=True,
    )

    stopping = False

    def _on_signal(signum, _frame):  # type: ignore[no-untyped-def]
        nonlocal stopping
        print(f"\n[uploader] caught signal {signum}, stopping", flush=True)
        stopping = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    while not stopping:
        elapsed = time.monotonic() - started_at
        # Sine bias period of 24 hours; amplitude 25 mg/dL.
        diurnal_bias = 25 * math.sin(elapsed * 2 * math.pi / 86400)
        target = baseline + diurnal_bias
        # Random step toward target plus jitter.
        step = random.gauss(0, volatility) + 0.05 * (target - sgv)
        sgv = max(40, min(400, int(round(sgv + step))))

        direction = _direction_for(prev_sgv, sgv)
        try:
            _post_entry(base_url, secret_hash, sgv, direction, device)
            print(
                f"[uploader] sgv={sgv} direction={direction} "
                f"(prev={prev_sgv}, target={target:.1f})",
                flush=True,
            )
        except urllib.error.HTTPError as exc:
            # 401 / 403 are permanent and won't recover by retrying;
            # bail with a non-zero exit so the operator sees the
            # misconfiguration immediately. Other HTTP codes (e.g.
            # 5xx, 429) are usually transient -- log + retry.
            if exc.code in (401, 403):
                print(
                    f"[uploader] FATAL: HTTP {exc.code} {exc.reason} -- "
                    f"check NS_API_SECRET; aborting.",
                    flush=True,
                )
                return 1
            print(f"[uploader] HTTP {exc.code}: {exc.reason}", flush=True)
        except urllib.error.URLError as exc:
            # DNS / hostname failures are permanent for the lifetime
            # of this process; transient TCP issues are not.
            # `socket.gaierror` covers Linux ("Name or service not known"),
            # macOS/BSD ("nodename nor servname"), and Windows
            # ("getaddrinfo failed") uniformly without OS-specific string
            # matching.
            if isinstance(exc.reason, socket.gaierror):
                print(
                    f"[uploader] FATAL: cannot resolve {base_url!r} "
                    f"({exc.reason}); aborting.",
                    flush=True,
                )
                return 1
            print(f"[uploader] network error: {exc.reason}", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep loop running
            print(f"[uploader] unexpected error: {exc}", flush=True)

        prev_sgv = sgv

        # Sleep in 1-second chunks so SIGINT lands quickly.
        slept = 0.0
        while slept < cadence and not stopping:
            time.sleep(min(1.0, cadence - slept))
            slept += 1.0

    return 0


if __name__ == "__main__":
    sys.exit(main())
