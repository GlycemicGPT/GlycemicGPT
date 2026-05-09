"""Multi-lens Nightscout emulator for GlycemicGPT contributors.

A test driver that pretends to be a real diabetic using Nightscout
with one of several closed-loop / CGM platforms. Lets contributors
who don't run Nightscout, don't have a CGM, don't have a pump, and
aren't diabetic verify their changes against realistic Nightscout
data.

NOT shipped in any production image. NOT imported by application
code. NOT a control algorithm. NOT a CGM replacement. Just a
contributor-facing test fixture.

Architecture: a shared physiology engine produces a continuous
stream of "what is happening to this simulated patient right now"
events (BG readings, meals, boluses, basal decisions, reservoir +
battery state). Each `Lens` renders that stream to one specific
platform's actual Nightscout wire format -- Loop's payloads look
like Loop, AAPS's look like AAPS, etc.

Currently shipped lenses:
  - loop       : Loop (Apple iPhone closed-loop, NS API v1, SHA-1 secret)
  - aaps_v1    : AndroidAPS NSClient legacy (NS API v1, SHA-1 secret)
  - aaps_v3    : AndroidAPS NSClientV3 (NS API v3, JWT subject)
  - trio       : Trio (iOS oref-derived, NS API v1, SHA-1 secret)
  - oref0      : OpenAPS oref0 (Raspberry Pi, the original oref impl)
  - xdrip4ios  : xDrip4iOS (iOS pure-CGM uploader, no closed-loop)
  - xdrip_plus : xDrip+ (Android pure-CGM uploader, predates xdrip4ios)

Planned (each its own PR -- see dev/README.md for status):
  - iaps, librelink_up, share2ns, tconnectsync, manual

Each lens is anchored to its source-of-truth document in the
external `bewest/rag-nightscout-ecosystem-alignment` repo, e.g.
Loop's behavior here mirrors `mapping/loop/nightscout-sync.md`.
That repo is reference, not authoritative -- when its claims and
the platform's upstream source disagree, upstream source wins.

Usage:
    NS_API_SECRET="<your-test-stack-secret>" \\
      python3 dev/ns_emulator.py --platform loop

Common env vars:
    NS_BASE_URL          default http://127.0.0.1:1337
    NS_API_SECRET        REQUIRED. Plaintext API_SECRET.
    NS_PLATFORM          default "loop". Same effect as --platform.
    NS_TIME_COMPRESSION  default 1 (realtime, 5-min CGM cadence).
                          >1 emits faster. >1 = entries arrive at
                          unrealistic wall-clock cadence (every 5/N
                          wall-seconds at compression N) but the
                          NS-side timestamps are always wall-clock,
                          never future-dated.
    NS_DURATION_HOURS    default 0 (unbounded -- run until Ctrl-C).
    NS_RANDOM_SEED       unset = truly random. Set int for repro.
    NS_STARTING_BG       default 120.

Per-lens env vars are documented inside each lens module.
Stops on Ctrl-C / SIGTERM. No state persistence -- restart fresh.
"""

from __future__ import annotations

import abc
import argparse
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
import uuid

# ---------------------------------------------------------------------------
# Profile / physiology constants
# ---------------------------------------------------------------------------

# 1 unit of insulin lowers BG by this much (realistic adult range
# is 30-70 mg/dL/U; pick a moderate value).
ISF_MGDL_PER_UNIT = 50.0
# 1 unit of insulin covers this many grams of carbs.
ICR_GRAMS_PER_UNIT = 10.0
# Total duration of insulin action in minutes.
DIA_MINUTES = 240
# Carb absorption window.
CARB_ABSORPTION_MINUTES = 90
# Scheduled basal rate (U/hr) when Loop is "running scheduled."
SCHEDULED_BASAL_U_HR = 0.8
# Loop allows temp basals up to this many U/hr (per pump's safety).
MAX_TEMP_BASAL_U_HR = 4.0
# Target glucose -- written to profile, used by correction + loop
# algorithm.
TARGET_BG_MGDL = 110.0
BG_FLOOR = 40
BG_CEIL = 400

# Pump reservoir capacity. Omnipod Eros pods hold 200 U; Medtronic
# 522/722 hold 300 U. We default to Omnipod since Loop on Omnipod
# is the most common deployment in the Loop community.
RESERVOIR_CAPACITY_U = 200.0
# Refill threshold -- when reservoir drops below this, simulate a
# pod / site change.
RESERVOIR_REFILL_THRESHOLD_U = 20.0
# Pump battery drain rate -- Omnipod pods don't really drain (they
# have a non-replaceable battery and last 72h regardless), but we
# model a slow drain to exercise the dashboard's battery widget.
PUMP_BATTERY_DRAIN_PCT_PER_HR = 0.5
# iPhone battery drain rate -- typical idle phone running Loop in
# the background. Charging events possible.
PHONE_BATTERY_DRAIN_PCT_PER_HR = 2.5
# When the phone hits this percent it starts charging (model a
# user plugging in). Charges back to 100% at this rate.
PHONE_BATTERY_CHARGE_THRESHOLD = 25
PHONE_BATTERY_CHARGE_PCT_PER_HR = 30.0

# Meal-window probabilities (per 5-min tick inside the window).
MEAL_TICK_PROBABILITY = 0.18
MEAL_WINDOWS = [
    (7, 9),  # breakfast
    (12, 13),  # lunch
    (18, 20),  # dinner
]
SNACK_TICK_PROBABILITY = 0.04
SNACK_WINDOWS = [(10, 11), (15, 16)]

# Correction trigger: BG above this AND IoB below this AND time
# since last correction at least N min.
CORRECTION_BG_THRESHOLD = 200
CORRECTION_IOB_CEILING = 1.5
CORRECTION_COOLDOWN_MIN = 90

# Dawn phenomenon: 4-7 am, peaks ~8 mg/dL/hr at the strongest.
DAWN_START_HOUR = 4
DAWN_END_HOUR = 7
DAWN_PEAK_DELTA_PER_HOUR = 8.0

# Loop's algorithm: temp basal duration is always 30 minutes per
# Loop's source (see mapping/loop/quirks.md "Temp Basal 30-Minute
# Duration"). Duration ≤ 1.05 × delta is treated as instant; we
# stay at 30 min so we're never in the instant regime.
LOOP_TEMP_BASAL_DURATION_MIN = 30


# ---------------------------------------------------------------------------
# Physiology engine -- platform-agnostic
# ---------------------------------------------------------------------------


class _Bolus:
    """A single bolus delivery, tracked until DIA elapses.

    Linear-decay model: at t=0 the full units are 'on board', at
    t=DIA all units have cleared. Real insulin curves are
    bi-exponential with a peak at 60-90 min, but linear is good
    enough for our use case and dramatically simpler.
    """

    __slots__ = ("units", "delivered_at_min")

    def __init__(self, units: float, delivered_at_min: float):
        self.units = units
        self.delivered_at_min = delivered_at_min

    def remaining_at(self, sim_minute: float) -> float:
        elapsed = sim_minute - self.delivered_at_min
        if elapsed <= 0:
            return self.units
        if elapsed >= DIA_MINUTES:
            return 0.0
        return self.units * (1.0 - elapsed / DIA_MINUTES)

    def cleared_in_interval(self, prev_min: float, curr_min: float) -> float:
        return self.remaining_at(prev_min) - self.remaining_at(curr_min)


class _CarbEvent:
    """A single meal's carbs, tracked until absorption is complete.

    Linear absorption: at t=0 all carbs are pending, at
    t=CARB_ABSORPTION_MINUTES all have been absorbed.
    """

    __slots__ = ("grams", "ingested_at_min")

    def __init__(self, grams: float, ingested_at_min: float):
        self.grams = grams
        self.ingested_at_min = ingested_at_min

    def cob_at(self, sim_minute: float) -> float:
        elapsed = sim_minute - self.ingested_at_min
        if elapsed <= 0:
            return self.grams
        if elapsed >= CARB_ABSORPTION_MINUTES:
            return 0.0
        return self.grams * (1.0 - elapsed / CARB_ABSORPTION_MINUTES)

    def absorbed_in_interval(self, prev_min: float, curr_min: float) -> float:
        return self.cob_at(prev_min) - self.cob_at(curr_min)


class PatientState:
    """The simulated patient's full physiological + device state.

    Sim-time drives physiology decisions (insulin / carb decay,
    meal-window hour-of-day, dawn-phenomenon bias). Wall-clock
    timestamps for NS payloads are computed once per tick in the
    main loop and passed down -- never derived from sim_time, since
    sim_time runs faster than wall clock under any compression > 1.

    Pump + uploader state (reservoir, batteries, suspended,
    temp_basal_*) is updated in lock-step with physiology so each
    lens can read a consistent snapshot when rendering its NS
    payloads.
    """

    def __init__(
        self,
        starting_bg: float,
        starting_sim_time: datetime.datetime,
    ):
        # Glucose / insulin / carb state.
        self.bg = float(starting_bg)
        self.sim_time = starting_sim_time
        self.sim_minute = 0.0
        self.boluses: list[_Bolus] = []
        # Running sum of all delivered insulin since simulation start
        # (units). The `boluses` list above only retains DIA-active
        # entries (advance_5_min prunes them after ~4h), so summing
        # `b.units for b in boluses` undercounts cumulative delivery
        # on long soak runs -- which broke the lens's running-TDD
        # estimate. This running total is monotonically increasing
        # for the life of the PatientState; pruning DIA-expired
        # entries from `boluses` does not affect it.
        self.total_bolus_units_delivered: float = 0.0
        self.carb_events: list[_CarbEvent] = []
        self.last_correction_min: float = -math.inf
        # Wall-clock instant of the most recent bolus delivery (any
        # kind). None until the first bolus fires. AAPS / oref
        # devicestatus carries this in `openaps.iob.lastBolusTime`
        # so the dashboard's bolus-detail view can show "last
        # bolus N minutes ago" without scanning treatments.
        self.last_bolus_at: datetime.datetime | None = None
        # (date_iso, "meal"|"snack", window_idx) -- prevents 4 dinners.
        self._consumed_windows: set[tuple[str, str, int]] = set()

        # Pump state.
        self.reservoir_u = RESERVOIR_CAPACITY_U
        self.pump_battery_pct: float = 100.0
        self.pump_suspended = False
        # Current temp basal: rate U/hr and remaining duration min.
        # On every loop cycle we set a fresh 30-min temp; in between
        # cycles, this counts down. When it hits 0 we revert to
        # scheduled basal (modelled as scheduled_basal_u_hr applied
        # for any non-temp time -- but realistically the loop sets
        # a temp every cycle so this should rarely deplete).
        self.temp_basal_rate_u_hr: float = SCHEDULED_BASAL_U_HR
        self.temp_basal_remaining_min: float = 0.0

        # Uploader (phone) state.
        self.phone_battery_pct: float = 80.0
        self.phone_is_charging = False

    # ---- read-only views ------------------------------------------------

    @property
    def iob(self) -> float:
        return sum(b.remaining_at(self.sim_minute) for b in self.boluses)

    @property
    def cob(self) -> float:
        return sum(c.cob_at(self.sim_minute) for c in self.carb_events)

    @property
    def current_basal_u_hr(self) -> float:
        if self.pump_suspended:
            return 0.0
        if self.temp_basal_remaining_min > 0:
            return self.temp_basal_rate_u_hr
        return SCHEDULED_BASAL_U_HR

    # ---- mutations ------------------------------------------------------

    def deliver_bolus(
        self, units: float, *, at: datetime.datetime | None = None
    ) -> None:
        if units <= 0:
            return
        self.boluses.append(_Bolus(units, self.sim_minute))
        self.total_bolus_units_delivered += units
        self.reservoir_u = max(0.0, self.reservoir_u - units)
        if at is not None:
            self.last_bolus_at = at

    def consume_carbs(self, grams: float) -> None:
        if grams <= 0:
            return
        self.carb_events.append(_CarbEvent(grams, self.sim_minute))

    def set_temp_basal(self, rate_u_hr: float, duration_min: float) -> None:
        self.temp_basal_rate_u_hr = max(0.0, min(MAX_TEMP_BASAL_U_HR, rate_u_hr))
        self.temp_basal_remaining_min = duration_min

    def maybe_refill_reservoir(self) -> bool:
        """If the reservoir hit the threshold, simulate a pod change.

        Returns True if a refill happened this tick (the lens may
        want to post a Site Change treatment).

        On Omnipod (the modeled pump) each pod ships with its own
        non-replaceable battery, so a pod swap restores both the
        reservoir AND the battery to fresh. Without this reset, a
        long-running emulator drains pump_battery_pct toward 0
        across many simulated pod changes, which contradicts the
        device-state story the lens is rendering.
        """
        if self.reservoir_u <= RESERVOIR_REFILL_THRESHOLD_U:
            self.reservoir_u = RESERVOIR_CAPACITY_U
            self.pump_battery_pct = 100.0
            return True
        return False

    # ---- main step ------------------------------------------------------

    def advance_5_min(self) -> None:
        """Advance 5 simulated minutes; update BG + device state."""
        prev_min = self.sim_minute
        new_min = prev_min + 5.0

        # Insulin effect: total units cleared in this slice times
        # ISF, working downward on BG.
        insulin_units_cleared = sum(
            b.cleared_in_interval(prev_min, new_min) for b in self.boluses
        )
        insulin_delta = -insulin_units_cleared * ISF_MGDL_PER_UNIT

        # Carb effect: 1g carb without insulin raises BG by ISF/ICR.
        carb_grams_absorbed = sum(
            c.absorbed_in_interval(prev_min, new_min) for c in self.carb_events
        )
        carb_delta = carb_grams_absorbed * (ISF_MGDL_PER_UNIT / ICR_GRAMS_PER_UNIT)

        # Dawn phenomenon: bias upward 4-7 am sim-time.
        next_sim = self.sim_time + datetime.timedelta(minutes=5)
        dawn_delta = 0.0
        hour_frac = next_sim.hour + next_sim.minute / 60.0
        if DAWN_START_HOUR <= hour_frac <= DAWN_END_HOUR:
            window_pos = (hour_frac - DAWN_START_HOUR) / (
                DAWN_END_HOUR - DAWN_START_HOUR
            )
            envelope = math.sin(window_pos * math.pi)
            dawn_delta = envelope * DAWN_PEAK_DELTA_PER_HOUR * (5 / 60)

        noise = random.gauss(0, 1.5)

        self.bg = max(
            BG_FLOOR,
            min(BG_CEIL, self.bg + insulin_delta + carb_delta + dawn_delta + noise),
        )
        self.sim_minute = new_min
        self.sim_time = next_sim

        # Pump state update: deplete reservoir by basal usage during
        # this slice, drain pump battery by clock time.
        basal_u_used = self.current_basal_u_hr * (5.0 / 60.0)
        self.reservoir_u = max(0.0, self.reservoir_u - basal_u_used)
        self.pump_battery_pct = max(
            0.0, self.pump_battery_pct - PUMP_BATTERY_DRAIN_PCT_PER_HR * (5.0 / 60.0)
        )
        self.temp_basal_remaining_min = max(0.0, self.temp_basal_remaining_min - 5.0)

        # Phone uploader battery.
        if self.phone_is_charging:
            self.phone_battery_pct = min(
                100.0,
                self.phone_battery_pct + PHONE_BATTERY_CHARGE_PCT_PER_HR * (5.0 / 60.0),
            )
            if self.phone_battery_pct >= 100.0:
                self.phone_is_charging = False
        else:
            self.phone_battery_pct = max(
                0.0,
                self.phone_battery_pct - PHONE_BATTERY_DRAIN_PCT_PER_HR * (5.0 / 60.0),
            )
            if self.phone_battery_pct <= PHONE_BATTERY_CHARGE_THRESHOLD:
                self.phone_is_charging = True

        # GC fully-decayed boluses / carbs to keep lists bounded.
        self.boluses = [
            b for b in self.boluses if b.remaining_at(self.sim_minute) > 1e-6
        ]
        self.carb_events = [
            c for c in self.carb_events if c.cob_at(self.sim_minute) > 1e-6
        ]

    # ---- meal / correction decisions ------------------------------------

    def maybe_meal(self) -> tuple[float, float] | None:
        """Decide if a meal happens this tick. Returns (carbs, bolus).

        At most one meal per (kind, window, day): once dinner has
        fired today, no further dinners can fire in the same 18-20
        window today even if the dice keep coming up under the
        threshold.
        """
        hour = self.sim_time.hour
        date_iso = self.sim_time.date().isoformat()

        meal_window = next(
            ((i, w) for i, w in enumerate(MEAL_WINDOWS) if w[0] <= hour < w[1]),
            None,
        )
        snack_window = next(
            ((i, w) for i, w in enumerate(SNACK_WINDOWS) if w[0] <= hour < w[1]),
            None,
        )

        if meal_window is not None:
            idx, _ = meal_window
            key = (date_iso, "meal", idx)
            if key in self._consumed_windows:
                return None
            if random.random() < MEAL_TICK_PROBABILITY:
                self._consumed_windows.add(key)
                carbs = random.uniform(40, 75)
                return carbs, round(carbs / ICR_GRAMS_PER_UNIT, 2)
            return None

        if snack_window is not None:
            idx, _ = snack_window
            key = (date_iso, "snack", idx)
            if key in self._consumed_windows:
                return None
            if random.random() < SNACK_TICK_PROBABILITY:
                self._consumed_windows.add(key)
                carbs = random.uniform(15, 30)
                return carbs, round(carbs / ICR_GRAMS_PER_UNIT, 2)
            return None

        return None

    def maybe_correction(self) -> float | None:
        if self.bg <= CORRECTION_BG_THRESHOLD:
            return None
        if self.iob >= CORRECTION_IOB_CEILING:
            return None
        if self.sim_minute - self.last_correction_min < CORRECTION_COOLDOWN_MIN:
            return None
        units = round((self.bg - TARGET_BG_MGDL) / ISF_MGDL_PER_UNIT, 2)
        if units < 0.1:
            return None
        return units

    def predict_glucose(self, horizon_min: int = 30) -> list[int]:
        """Project BG forward `horizon_min` minutes in 5-min steps.

        Uses the same physiology used by the live state machine:
        insulin still on board lowers BG as it decays; carbs still
        on board raise it as they absorb. Mild drift toward target
        so a stable BG with no active insulin / carbs converges.
        """
        steps = max(1, horizon_min // 5)
        out: list[int] = [int(round(self.bg))]
        proj_bg = self.bg
        for step in range(1, steps + 1):
            prev_future_min = self.sim_minute + 5 * (step - 1)
            future_min = self.sim_minute + 5 * step
            insulin_cleared = sum(
                b.cleared_in_interval(prev_future_min, future_min) for b in self.boluses
            )
            carbs_absorbed = sum(
                c.absorbed_in_interval(prev_future_min, future_min)
                for c in self.carb_events
            )
            delta = -insulin_cleared * ISF_MGDL_PER_UNIT + carbs_absorbed * (
                ISF_MGDL_PER_UNIT / ICR_GRAMS_PER_UNIT
            )
            delta += (TARGET_BG_MGDL - proj_bg) * 0.02
            proj_bg = max(BG_FLOOR, min(BG_CEIL, proj_bg + delta))
            out.append(int(round(proj_bg)))
        return out


# ---------------------------------------------------------------------------
# Loop-cycle decision: what temp basal does Loop set?
# ---------------------------------------------------------------------------


def loop_temp_basal_decision(state: PatientState) -> float:
    """Approximate Loop's temp-basal recommendation.

    Real Loop runs a prediction-based controller (LoopMath) that
    weighs IoB, COB, predicted glucose, and momentum to choose a
    temp basal rate that drives predicted BG to target while
    respecting safety bounds. We approximate with a simple
    proportional rule on predicted-BG-at-30-min:

        predicted_30min < target - 30  ->  rate = 0  (suspend-equivalent)
        predicted_30min < target - 10  ->  rate = scheduled * 0.5
        predicted_30min > target + 30  ->  rate = scheduled * 2.0
        predicted_30min > target + 10  ->  rate = scheduled * 1.3
        else                            ->  rate = scheduled

    That captures the right signal for exercising Nightscout's
    devicestatus + temp-basal treatment streams without trying to
    re-implement Loop's full algorithm.
    """
    predicted = state.predict_glucose(horizon_min=30)
    p30 = predicted[-1]
    scheduled = SCHEDULED_BASAL_U_HR
    if p30 < TARGET_BG_MGDL - 30:
        return 0.0
    if p30 < TARGET_BG_MGDL - 10:
        return round(scheduled * 0.5, 3)
    if p30 > TARGET_BG_MGDL + 30:
        return round(min(MAX_TEMP_BASAL_U_HR, scheduled * 2.0), 3)
    if p30 > TARGET_BG_MGDL + 10:
        return round(scheduled * 1.3, 3)
    return scheduled


# ---------------------------------------------------------------------------
# HTTP helpers (auth-agnostic; each lens decides how to set headers)
# ---------------------------------------------------------------------------


def hash_secret_sha1(secret: str) -> str:
    return hashlib.sha1(secret.encode("utf-8")).hexdigest()


def iso_z(t: datetime.datetime) -> str:
    """ISO-8601 with Z suffix, milliseconds -- matches what Nightscout
    serializes itself."""
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def http_post(base_url: str, path: str, headers: dict[str, str], payload) -> None:
    """POST JSON; raise HTTPError on non-2xx (urlopen does that for us)."""
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15):
        pass


def http_get(base_url: str, path: str, headers: dict[str, str]):
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def direction_for(prev: float, curr: float) -> str:
    """Map per-tick BG delta to Dexcom's direction vocabulary."""
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


# ---------------------------------------------------------------------------
# Lens contract
# ---------------------------------------------------------------------------


class Lens(abc.ABC):
    """Abstract base: every platform's emulation layer.

    The shared physiology engine produces state; the lens renders
    that state to one specific platform's Nightscout wire format.

    Each tick (5 simulated min) the main loop calls, in order:
      1. lens.on_tick_start(state, posted_at) -- pre-physiology hook
         (lenses may set new temp basals here, etc.)
      2. state.advance_5_min()
      3. lens.post_entry(state, prev_bg, posted_at)
      4. lens.post_devicestatus(state, posted_at)
      5. lens.post_meal_bolus / post_correction_bolus / post_temp_basal
         as physiology dictates

    Plus on startup: lens.ensure_profile() once.
    """

    name: str  # short identifier, e.g. "loop"

    def __init__(
        self, base_url: str, api_secret: str, device_label: str | None = None
    ) -> None:
        self.base_url = base_url
        self.api_secret = api_secret
        # Each lens may override; default uses SHA-1 hashed header.
        self._auth_headers = {"api-secret": hash_secret_sha1(api_secret)}
        self.device_label = device_label or self.default_device_label()

    @classmethod
    @abc.abstractmethod
    def default_device_label(cls) -> str:
        """The string this lens identifies as in NS `device` /
        `enteredBy` fields."""

    @abc.abstractmethod
    def ensure_profile(self) -> None:
        """Post a profile snapshot if none exists. Called once."""

    @abc.abstractmethod
    def on_tick_start(self, state: PatientState, posted_at: datetime.datetime) -> None:
        """Hook before physiology advances.

        For closed-loop lenses (Loop, AAPS, Trio), this is where the
        loop algorithm decides a new temp basal and applies it to
        state. For passive lenses (xDrip uploaders), this is a noop.
        """

    @abc.abstractmethod
    def post_entry(
        self,
        state: PatientState,
        prev_bg: float,
        posted_at: datetime.datetime,
    ) -> None:
        """POST one CGM entry."""

    @abc.abstractmethod
    def post_devicestatus(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """POST one devicestatus (loop / pump / uploader subtree)."""

    @abc.abstractmethod
    def post_meal_bolus(
        self,
        state: PatientState,
        carbs_g: float,
        bolus_u: float,
        posted_at: datetime.datetime,
    ) -> None:
        """POST a meal bolus treatment (carbs + insulin together)."""

    @abc.abstractmethod
    def post_correction_bolus(
        self,
        state: PatientState,
        units: float,
        posted_at: datetime.datetime,
    ) -> None:
        """POST a correction bolus treatment."""

    @abc.abstractmethod
    def post_temp_basal(
        self,
        state: PatientState,
        rate_u_hr: float,
        duration_min: int,
        posted_at: datetime.datetime,
    ) -> None:
        """POST a temp-basal treatment.

        Loop: every 5 sim-min the algorithm decides a 30-min temp,
        regardless of whether rate changed (so the pump always has
        a fresh temp). Other lenses post when rate changes only.
        """

    def post_site_change(  # noqa: B027 - intentional non-abstract default
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """POST a site / pod change treatment when the reservoir
        runs low. Default impl is a noop -- not every platform
        models this. Loop overrides; xDrip-style uploaders
        legitimately don't (they have no pump state to track)."""


# ---------------------------------------------------------------------------
# LoopLens: Apple iPhone closed-loop, NS API v1, SHA-1 api-secret
# ---------------------------------------------------------------------------
#
# Source-of-truth document:
#   bewest/rag-nightscout-ecosystem-alignment/mapping/loop/nightscout-sync.md
#
# Loop posts to:
#   POST /api/v1/entries.json       -- CGM
#   POST /api/v1/treatments.json    -- doses (bolus, temp basal, suspend)
#   POST /api/v1/devicestatus.json  -- loop status, pump status, uploader
#   POST /api/v1/profile.json       -- therapy settings (optional)
#
# Identity: every dose carries a `syncIdentifier` UUID so Nightscout
# (and downstream readers like GlycemicGPT) can dedupe across
# overlapping uploads.
#
# `enteredBy` is "loop://<deviceName>/Loop/<version>" -- we model it
# as "loop://iPhone/Loop/3.4.5" by default.


LOOP_VERSION = "3.4.5"
LOOP_PUMP_MANUFACTURER = "Insulet"
LOOP_PUMP_MODEL = "Eros"
LOOP_INSULIN_TYPE = "Humalog"


class LoopLens(Lens):
    name = "loop"

    @classmethod
    def default_device_label(cls) -> str:
        # Real Loop's `enteredBy` is `loop://<UIDevice.name>` -- NOT
        # the longer `loop://<device>/Loop/<version>` shape that
        # appears in some older docs. Verified against real Loop
        # treatment fixtures in
        # bewest/rag-nightscout-ecosystem-alignment/tools/ns2parquet/fixtures/.
        return "loop://iPhone"

    # ---- profile --------------------------------------------------------

    def ensure_profile(self) -> None:
        """Loop's profile upload is sparse compared to AAPS / Trio --
        it carries the therapy settings (basal schedule, ISF, ICR,
        target ranges) but not pump-specific limits. We post just
        enough to populate `nightscout_profile_snapshots` and let
        the GlycemicGPT onboarding flow pre-fill defaults."""
        try:
            existing = http_get(
                self.base_url, "/api/v1/profile.json", self._auth_headers
            )
            if existing:
                return
        except urllib.error.HTTPError:
            pass

        now_iso = iso_z(datetime.datetime.now(datetime.UTC))
        profile_name = "Default"
        payload = {
            "defaultProfile": profile_name,
            "store": {
                profile_name: {
                    "dia": str(DIA_MINUTES // 60),
                    "carbratio": [{"time": "00:00", "value": ICR_GRAMS_PER_UNIT}],
                    "sens": [{"time": "00:00", "value": ISF_MGDL_PER_UNIT}],
                    "basal": [{"time": "00:00", "value": SCHEDULED_BASAL_U_HR}],
                    "target_low": [{"time": "00:00", "value": TARGET_BG_MGDL - 10}],
                    "target_high": [{"time": "00:00", "value": TARGET_BG_MGDL + 10}],
                    "carbs_hr": "20",
                    "delay": "20",
                    "timezone": "UTC",
                    "units": "mg/dl",
                }
            },
            "startDate": now_iso,
            "mills": str(int(time.time() * 1000)),
            "units": "mg/dl",
        }
        http_post(
            self.base_url,
            "/api/v1/profile.json",
            self._auth_headers,
            [payload],  # NS v1 profile is array-wrapped per Mongo insert convention
        )

    # ---- per-tick hooks -------------------------------------------------

    def on_tick_start(self, state: PatientState, posted_at: datetime.datetime) -> None:
        """Loop's algorithm runs every 5 min and chooses a temp basal.

        We model that decision and apply it to state BEFORE
        physiology advances, so the new basal affects this tick's
        BG delta. The corresponding Temp Basal treatment is posted
        AFTER advance_5_min completes (in the main loop), so its
        timestamp matches the entry it accompanies.
        """
        rate = loop_temp_basal_decision(state)
        state.set_temp_basal(rate, LOOP_TEMP_BASAL_DURATION_MIN)

    # ---- entries --------------------------------------------------------

    def post_entry(
        self,
        state: PatientState,
        prev_bg: float,
        posted_at: datetime.datetime,
    ) -> None:
        payload = [
            {
                "type": "sgv",
                "sgv": int(round(state.bg)),
                "direction": direction_for(prev_bg, state.bg),
                "date": int(posted_at.timestamp() * 1000),
                "dateString": iso_z(posted_at),
                "device": self.device_label,
            }
        ]
        http_post(self.base_url, "/api/v1/entries.json", self._auth_headers, payload)

    # ---- devicestatus ---------------------------------------------------

    def post_devicestatus(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        predicted = state.predict_glucose(horizon_min=360)  # Loop posts up to 6h
        loop_subtree = {
            "name": "Loop",
            "version": f"Loop {LOOP_VERSION}",
            "timestamp": iso_z(posted_at),
            "iob": {
                "timestamp": iso_z(posted_at),
                "iob": round(state.iob, 3),
            },
            "cob": {
                "timestamp": iso_z(posted_at),
                "cob": round(state.cob, 1),
            },
            "predicted": {
                "startDate": iso_z(posted_at),
                "values": predicted,
            },
            "recommendedBolus": 0.0,
            # Real Loop only includes `tempBasalAdjustment` when the
            # algorithm wants to change rate from current scheduled
            # (~17% of cycles per fixtures). Otherwise it omits the
            # subobject and only carries `timestamp` + `bolusVolume`.
            # We mirror that by including `tempBasalAdjustment` only
            # when the chosen rate diverges from scheduled basal.
            "automaticDoseRecommendation": {
                "timestamp": iso_z(posted_at),
                "bolusVolume": 0.0,
                **(
                    {
                        "tempBasalAdjustment": {
                            "rate": state.temp_basal_rate_u_hr,
                            "duration": LOOP_TEMP_BASAL_DURATION_MIN * 60,
                        }
                    }
                    if abs(state.temp_basal_rate_u_hr - SCHEDULED_BASAL_U_HR) > 1e-6
                    else {}
                ),
            },
            "enacted": {
                "timestamp": iso_z(posted_at),
                "rate": state.temp_basal_rate_u_hr,
                # `enacted.duration` is in MINUTES on the wire --
                # verified against 218 real Loop fixture samples
                # showing `duration: 30`.
                "duration": LOOP_TEMP_BASAL_DURATION_MIN,
                "received": True,
                "bolusVolume": 0.0,
            },
        }

        pump_subtree = {
            "clock": iso_z(posted_at),
            "pumpID": "12345678",  # arbitrary pod serial
            "manufacturer": LOOP_PUMP_MANUFACTURER,
            "model": LOOP_PUMP_MODEL,
            "iob": None,  # Loop sets pump.iob = null; it's authoritative on loop.iob
            "battery": {"percent": int(state.pump_battery_pct)},
            "suspended": state.pump_suspended,
            "bolusing": False,
            "reservoir": round(state.reservoir_u, 1),
            "secondsFromGMT": 0,
        }

        uploader_subtree = {
            "name": "iPhone",
            "battery": int(state.phone_battery_pct),
            "isCharging": state.phone_is_charging,
            "timestamp": iso_z(posted_at),
        }

        payload = [
            {
                "device": self.device_label,
                "created_at": iso_z(posted_at),
                "loop": loop_subtree,
                "pump": pump_subtree,
                "uploader": uploader_subtree,
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/devicestatus.json",
            self._auth_headers,
            payload,
        )

    # ---- treatments -----------------------------------------------------

    def _new_sync_id(self) -> str:
        """One UUID per dose, mirroring how Loop generates them in
        DoseEntry.swift."""
        return str(uuid.uuid4())

    def _bolus_payload(
        self,
        units: float,
        posted_at: datetime.datetime,
        *,
        event_type: str,
    ) -> dict:
        """Bolus shape verified against real Loop fixtures (see
        ns2parquet/fixtures/patient_d_treatments.json: 121
        `Correction Bolus` records). Loop carries `programmed`,
        `unabsorbed: 0`, and `type: "normal"` in addition to
        `insulin` / `amount`."""
        return {
            "eventType": event_type,
            "timestamp": iso_z(posted_at),
            "created_at": iso_z(posted_at),
            "enteredBy": self.device_label,
            "insulin": units,
            "amount": units,
            "programmed": units,
            "unabsorbed": 0,
            "duration": 0,
            "automatic": False,
            "type": "normal",
            "bolusType": "Normal",
            "insulinType": LOOP_INSULIN_TYPE,
            "syncIdentifier": self._new_sync_id(),
        }

    def post_meal_bolus(
        self,
        state: PatientState,
        carbs_g: float,
        bolus_u: float,
        posted_at: datetime.datetime,
    ) -> None:
        # Real Loop splits a meal into TWO treatment records: a
        # `Carb Correction` (carbs only, no insulin field) and a
        # separate `Correction Bolus` (insulin only). It does NOT
        # use the `Meal Bolus` eventType -- that's a Trio / AAPS
        # pattern. Verified against real Loop fixtures.
        carb_payload = {
            "eventType": "Carb Correction",
            "timestamp": iso_z(posted_at),
            "created_at": iso_z(posted_at),
            "userEnteredAt": iso_z(posted_at),
            "enteredBy": self.device_label,
            "carbs": round(carbs_g, 1),
            "absorptionTime": int(CARB_ABSORPTION_MINUTES * 60),
            "foodType": "",
            "syncIdentifier": self._new_sync_id(),
        }
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            [carb_payload],
        )
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            [self._bolus_payload(bolus_u, posted_at, event_type="Correction Bolus")],
        )

    def post_correction_bolus(
        self,
        state: PatientState,
        units: float,
        posted_at: datetime.datetime,
    ) -> None:
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            [self._bolus_payload(units, posted_at, event_type="Correction Bolus")],
        )

    def post_temp_basal(
        self,
        state: PatientState,
        rate_u_hr: float,
        duration_min: int,
        posted_at: datetime.datetime,
    ) -> None:
        # Loop posts a Temp Basal treatment for every loop cycle, even
        # when the rate didn't change -- that lets the pump always
        # have a fresh temp running. See mapping/loop/quirks.md
        # "Temp Basal 30-Minute Duration". `duration` here is in
        # SECONDS per NightscoutKit's TempBasalNightscoutTreatment;
        # `enacted.duration` in devicestatus is in MINUTES per real
        # fixtures (verified: 218 of 450 sample devicestatus rows
        # have `enacted.duration: 30`). Loop normalizes `carbs` and
        # `insulin` to null on temp-basal records so downstream
        # readers see consistent shapes.
        delivered = round(rate_u_hr * (duration_min / 60.0), 3)
        payload = [
            {
                "eventType": "Temp Basal",
                "timestamp": iso_z(posted_at),
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "temp": "Absolute",
                "rate": rate_u_hr,
                "absolute": rate_u_hr,
                "duration": duration_min * 60,
                "amount": delivered,
                "automatic": True,
                "carbs": None,
                "insulin": None,
                "insulinType": LOOP_INSULIN_TYPE,
                "syncIdentifier": self._new_sync_id(),
            }
        ]
        http_post(self.base_url, "/api/v1/treatments.json", self._auth_headers, payload)

    def post_site_change(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        # Loop's site-change is posted as a Pump Site Change event.
        payload = [
            {
                "eventType": "Pump Site Change",
                "timestamp": iso_z(posted_at),
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "notes": "Reservoir refilled (emulated)",
                "syncIdentifier": self._new_sync_id(),
            }
        ]
        http_post(self.base_url, "/api/v1/treatments.json", self._auth_headers, payload)


# ---------------------------------------------------------------------------
# AapsV1Lens: AndroidAPS NSClient (legacy), NS API v1, SHA-1 api-secret
# ---------------------------------------------------------------------------
#
# Source-of-truth documents:
#   bewest/rag-nightscout-ecosystem-alignment/mapping/aaps/nightscout-sync.md
#   bewest/rag-nightscout-ecosystem-alignment/mapping/aaps/nsclient-schema.md
#
# Verified against real AAPS-uploaded fixtures in that repo's
# tools/ns2parquet/fixtures/odc_*_devicestatus.json and
# odc_*_treatments.json (133 AAPS treatments, 547 AAPS devicestatus).
#
# AAPS posts to:
#   POST /api/v1/entries.json        -- CGM
#   POST /api/v1/treatments.json     -- doses (bolus, SMB, temp basal)
#   POST /api/v1/devicestatus.json   -- openaps subtree (no loop subtree)
#   POST /api/v1/profile.json        -- therapy settings
#
# Identity / dedupe: AAPS uses a composite (`pumpId`, `pumpType`,
# `pumpSerial`) for pump events plus an `identifier` UUID for
# everything else. Loop, by contrast, uses `syncIdentifier`.
#
# Wire-format differences from Loop:
# - `enteredBy` / `device` are both `"openaps://AndroidAPS"` (Loop:
#   `"loop://iPhone"`).
# - Meal Bolus is a SINGLE record carrying both carbs and insulin
#   (Loop splits into separate Carb Correction + Correction Bolus).
# - `SMB` is its own eventType for automated micro-boluses (Loop
#   has no SMB concept; auto-boluses come through normal channels).
# - DeviceStatus uses an `openaps` subtree (Loop uses `loop`). The
#   openaps shape is documented in oref-0 / oref-1 algorithm specs.
# - Predicted-glucose curves are nested as `predBGs.IOB[]`,
#   `predBGs.COB[]`, `predBGs.UAM[]`, `predBGs.ZT[]` -- separate
#   arrays per scenario, not one merged array (Loop merges into
#   `predicted.values[]`).
# - Temp Basal `duration` is in MINUTES on the wire (Loop uses
#   seconds for the same field).
# - Pump telemetry (battery / reservoir) is OFTEN ABSENT from AAPS
#   devicestatus -- AAPS pump drivers vary in what they expose.
#   We emit a pump subtree anyway so the dashboard's pump-status
#   widget has data; real AAPS users with limited pump drivers will
#   see those widgets blank, which is correct.


AAPS_VERSION = "3.2.0.4"
AAPS_PUMP_TYPE = "ACCU_CHEK_INSIGHT_BLUETOOTH"  # common AAPS pump
AAPS_PUMP_SERIAL = "AC1234567"
AAPS_INSULIN_TYPE = "Novorapid"  # AAPS popular EU choice
AAPS_DEVICE_LABEL = "openaps://AndroidAPS"


class AapsV1Lens(Lens):
    name = "aaps_v1"

    def __init__(
        self, base_url: str, api_secret: str, device_label: str | None = None
    ) -> None:
        super().__init__(base_url, api_secret, device_label)
        # Real-world AAPS: most users have "Upload temp basals" OFF in
        # NSClient settings (privacy + Mongo space). Survey of one
        # patient's 133 treatments: 0 Temp Basal records. Match that
        # by default; opt-in via env when the contributor wants
        # exhaustive temp-basal-mapper coverage.
        self._upload_temp_basals = os.environ.get(
            "NS_AAPS_UPLOAD_TEMP_BASALS", "false"
        ).lower() in ("1", "true", "yes")
        # Once-per-sim-day gates for shapes that don't fire every
        # cycle: Profile Switch (e.g., "Exercise" mode 17:00-19:00)
        # and Temporary Target (e.g., morning exercise target).
        # Track only the last-fired ISO date so memory doesn't grow
        # across multi-day soak runs.
        self._last_profile_switch_date: str | None = None
        self._last_temp_target_date: str | None = None
        # RNG for the manual-vs-SMB correction split. Honor
        # NS_RANDOM_SEED so reproducible runs (documented in the
        # common-tunables table) are actually reproducible end-to-end.
        # Guard the int() so a malformed seed (e.g., the lens being
        # instantiated outside main() with a bad env value) falls back
        # to an unseeded RNG instead of crashing the constructor.
        seed_env = os.environ.get("NS_RANDOM_SEED")
        try:
            self._rng = (
                random.Random(int(seed_env)) if seed_env else random.Random()
            )
        except ValueError:
            self._rng = random.Random()

    @classmethod
    def default_device_label(cls) -> str:
        return AAPS_DEVICE_LABEL

    # ---- profile --------------------------------------------------------

    def ensure_profile(self) -> None:
        """AAPS profile uploads include the same fields as Loop's
        but with AAPS-specific keys for DIA (`dia_hours`), `units`,
        and timezone. Minimal shape that satisfies our profile
        snapshot translator + AAPS UI's expectations.
        """
        try:
            existing = http_get(
                self.base_url, "/api/v1/profile.json", self._auth_headers
            )
            if existing:
                return
        except urllib.error.HTTPError:
            pass

        body = self._build_profile_body()
        self._post_profile(body)

    def _build_profile_body(self) -> dict:
        """The AAPS profile shape -- shared by v1 and v3 (the v3 lens
        only changes the endpoint + JSON envelope, not the contents)."""
        now_iso = iso_z(datetime.datetime.now(datetime.UTC))
        profile_name = "AAPS"
        return {
            "defaultProfile": profile_name,
            "store": {
                profile_name: {
                    "dia": str(DIA_MINUTES // 60),
                    "carbratio": [{"time": "00:00", "value": ICR_GRAMS_PER_UNIT}],
                    "sens": [{"time": "00:00", "value": ISF_MGDL_PER_UNIT}],
                    "basal": [{"time": "00:00", "value": SCHEDULED_BASAL_U_HR}],
                    "target_low": [{"time": "00:00", "value": TARGET_BG_MGDL - 10}],
                    "target_high": [{"time": "00:00", "value": TARGET_BG_MGDL + 10}],
                    "carbs_hr": "20",
                    "delay": "20",
                    "timezone": "UTC",
                    "units": "mg/dl",
                }
            },
            "startDate": now_iso,
            # int (not str) -- matches the type used on this lens's
            # entries / treatments / devicestatus mills fields, and
            # the v3 lens's overlay. NS coerces, but staying
            # consistent avoids a type-mismatch read later.
            "mills": int(time.time() * 1000),
            "units": "mg/dl",
        }

    def _post_profile(self, body: dict) -> None:
        """V1 path: array body + /api/v1/profile.json + api-secret.
        V3 lens overrides this to POST a single doc to /api/v3/profile."""
        http_post(
            self.base_url, "/api/v1/profile.json", self._auth_headers, [body]
        )

    # ---- per-tick hooks -------------------------------------------------

    def on_tick_start(self, state: PatientState, posted_at: datetime.datetime) -> None:
        """Per-cycle hook: set new temp basal AND occasionally fire
        Profile Switch / Temporary Target events to exercise the
        translator's `_map_profile_switch` and `_map_temp_target`
        paths. These events fire at most once per sim-day at fixed
        slots (once a real AAPS user enables 'Exercise' mode in the
        morning, etc.).
        """
        rate = loop_temp_basal_decision(state)
        state.set_temp_basal(rate, LOOP_TEMP_BASAL_DURATION_MIN)

        # Once per sim-day, in the morning exercise window (6-7am),
        # fire a Temporary Target = "Exercise". Real AAPS users do
        # this to raise the algorithm's target during workouts.
        # Catch broadly: a hiccup posting one optional fixture event
        # must not crash the per-tick hook for the whole emulator.
        date_iso = state.sim_time.date().isoformat()
        hour = state.sim_time.hour
        if 6 <= hour < 7 and self._last_temp_target_date != date_iso:
            self._last_temp_target_date = date_iso
            try:
                self._post_temp_target(posted_at, target_mgdl=140, duration_min=60)
            except Exception as exc:  # noqa: BLE001
                print(f"[emu] aaps temp_target post failed: {exc}", flush=True)

        # Once per sim-day, in the late-afternoon "winding down for
        # the day" window (17-18), fire a Profile Switch = "Exercise"
        # at 130% (more insulin sensitivity). Real AAPS users use
        # profile switches for sick days, exercise periods, etc.
        if 17 <= hour < 18 and self._last_profile_switch_date != date_iso:
            self._last_profile_switch_date = date_iso
            try:
                self._post_profile_switch(
                    posted_at, profile="Exercise", percentage=130, duration_min=120
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[emu] aaps profile_switch post failed: {exc}", flush=True)

    # ---- entries --------------------------------------------------------

    def post_entry(
        self,
        state: PatientState,
        prev_bg: float,
        posted_at: datetime.datetime,
    ) -> None:
        # AAPS-uploaded entries carry an `app` field identifying the
        # uploader; the rest of the shape is the same as any other
        # uploader.
        body = self._build_entry_body(state, prev_bg, posted_at)
        self._post_entry(body, posted_at=posted_at)

    def _build_entry_body(
        self,
        state: PatientState,
        prev_bg: float,
        posted_at: datetime.datetime,
    ) -> dict:
        return {
            "type": "sgv",
            "sgv": int(round(state.bg)),
            "direction": direction_for(prev_bg, state.bg),
            "date": int(posted_at.timestamp() * 1000),
            "dateString": iso_z(posted_at),
            "device": self.device_label,
            "app": "AAPS",
        }

    def _post_entry(
        self, body: dict, *, posted_at: datetime.datetime
    ) -> None:
        """V1 path: array body to /api/v1/entries.json with api-secret.
        V3 lens overrides to POST single doc to /api/v3/entries with JWT.
        `posted_at` is unused here but the v3 override needs it for the
        v3 overlay -- kept on the signature so callers don't have to
        know which transport they're feeding (mirror of
        `_post_treatment`)."""
        del posted_at  # v1 doesn't need it
        http_post(
            self.base_url, "/api/v1/entries.json", self._auth_headers, [body]
        )

    # ---- devicestatus ---------------------------------------------------

    def _build_predbgs(self, state: PatientState) -> dict[str, list[int]]:
        """oref-style predBGs scenarios. Real AAPS posts up to 4 arrays:

        - IOB: prediction assuming no more carbs ingested
        - COB: prediction assuming all current COB absorbs
        - UAM: unannounced-meal prediction (algorithm guess)
        - ZT:  zero-temp prediction (assume basal stops)

        Our physiology produces one curve. Replicate it across the
        four scenarios with small per-scenario perturbations so the
        dashboard's predicted-curve widget (when it lands) sees the
        full AAPS shape.
        """
        base = state.predict_glucose(horizon_min=180)  # AAPS posts ~3h
        return {
            "IOB": [int(v) for v in base],
            # COB scenario: assume more carbs absorb -> slightly higher
            "COB": [int(min(BG_CEIL, v + max(0, state.cob * 0.5))) for v in base],
            # UAM scenario: assume an unannounced meal hits in ~30 min
            "UAM": [int(min(BG_CEIL, v + 5)) for v in base],
            # ZT scenario: assume basal stops -> drift up
            "ZT": [int(min(BG_CEIL, v + max(0, state.iob * 5))) for v in base],
        }

    def post_devicestatus(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        body = self._build_devicestatus_body(state, posted_at)
        self._post_devicestatus(body, posted_at=posted_at)

    def _post_devicestatus(
        self, body: dict, *, posted_at: datetime.datetime
    ) -> None:
        """V1 path: array body to /api/v1/devicestatus.json + api-secret.
        V3 overrides to POST single doc to /api/v3/devicestatus + JWT.
        `posted_at` is unused here but the v3 override needs it for the
        v3 overlay (mirror of `_post_treatment`)."""
        del posted_at  # v1 doesn't need it
        http_post(
            self.base_url,
            "/api/v1/devicestatus.json",
            self._auth_headers,
            [body],
        )

    def _build_devicestatus_body(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> dict:
        # `openaps` subtree mirrors the oref-1 / SMB algorithm's
        # output. Both `iob` and `suggested` are rich; `enacted`
        # mirrors `suggested` plus `received: true` and a timestamp.
        ts = iso_z(posted_at)
        # `lastBolusTime` is the wall-clock instant of the most
        # recent ACTUAL bolus, not "now". When no bolus has fired
        # yet in this run, AAPS posts 0; the dashboard interprets
        # that as "no bolus on record" and skips the "last bolus N
        # min ago" indicator.
        last_bolus_ms = (
            int(state.last_bolus_at.timestamp() * 1000)
            if state.last_bolus_at is not None
            else 0
        )
        iob_subtree = {
            "iob": round(state.iob, 3),
            "basaliob": round(state.iob * 0.4, 3),
            "bolussnooze": 0.0,
            "activity": round(state.iob * 0.0008, 6),
            "lastBolusTime": last_bolus_ms,
            "time": ts,
        }
        predicted = self._build_predbgs(state)
        suggested = {
            "temp": "absolute",
            "bg": int(round(state.bg)),
            "tick": "+0",
            "eventualBG": predicted["IOB"][-1]
            if predicted["IOB"]
            else int(round(state.bg)),
            "targetBG": int(TARGET_BG_MGDL),
            "insulinReq": 0.0,
            "reservoir": round(state.reservoir_u, 1),
            "deliverAt": ts,
            "sensitivityRatio": 1.0,
            "predBGs": predicted,
            "COB": round(state.cob, 1),
            "IOB": round(state.iob, 3),
            "rate": state.temp_basal_rate_u_hr,
            "duration": LOOP_TEMP_BASAL_DURATION_MIN,
            "reason": (
                "COB: {cob}, Dev: 0, BGI: 0, ISF: {isf}, "
                "CR: {cr}, Target: {target}, eventualBG: {ev}, "
                "rate: {rate}".format(
                    cob=round(state.cob, 1),
                    isf=ISF_MGDL_PER_UNIT,
                    cr=ICR_GRAMS_PER_UNIT,
                    target=int(TARGET_BG_MGDL),
                    ev=predicted["IOB"][-1] if predicted["IOB"] else "?",
                    rate=state.temp_basal_rate_u_hr,
                )
            ),
        }
        enacted = {
            **suggested,
            "received": True,
            "timestamp": ts,
        }

        # AAPS pump telemetry is variable across pump drivers. We
        # emit a pump subtree with battery + reservoir so the
        # dashboard widgets render. Real-world AAPS users with
        # limited pump drivers (e.g., virtual pump, some Roche
        # pumps) will have NO pump subtree at all -- our translator
        # handles that case (widgets show empty).
        pump_subtree = {
            "clock": ts,
            "battery": {"percent": int(state.pump_battery_pct)},
            "reservoir": round(state.reservoir_u, 1),
            "status": {"status": "normal", "suspended": state.pump_suspended},
        }

        # AAPS posts uploaderBattery as a TOP-LEVEL int (not nested
        # in an uploader subtree). Loop and Trio use a nested
        # uploader.battery instead. Our translator's NightscoutDeviceStatus
        # input model accepts both shapes (see nightscout/models.py).
        return {
            "device": self.device_label,
            "created_at": ts,
            "uploaderBattery": int(state.phone_battery_pct),
            "isCharging": state.phone_is_charging,
            "openaps": {
                "iob": iob_subtree,
                "suggested": suggested,
                "enacted": enacted,
                "version": AAPS_VERSION,
            },
            "pump": pump_subtree,
            "configuration": {
                "pump": AAPS_PUMP_TYPE,
                "version": AAPS_VERSION,
                "aps": "OpenAPSSMB",
            },
        }

    # ---- treatments -----------------------------------------------------

    def _aaps_pump_dedup_fields(self) -> dict:
        """AAPS pump composite dedup triple.

        Real AAPS clients post these on every pump-originated dose so
        a server-side reconciler can dedupe duplicate uploads. The
        GlycemicGPT translator drops the triple at metadata-allowlist
        time (`_pump_events_mapper.py:_METADATA_ALLOWLIST` does not
        include them; they're treated as identifier-shaped values
        and stripped). We emit them anyway for wire-format fidelity
        -- a future translator change that wants to use them will
        find them in the raw fixture data.
        """
        return {
            "pumpType": AAPS_PUMP_TYPE,
            "pumpSerial": AAPS_PUMP_SERIAL,
            # pumpId varies per dose -- the pump assigns a sequence
            # number per delivery. We use a random int in
            # [0, 1_000_000_000) so the composite key is
            # collision-resistant across a multi-day run without the
            # bookkeeping of a real autoincrement counter.
            "pumpId": int(uuid.uuid4().int % 1_000_000_000),
        }

    def _bolus_calculator_result(
        self, state: PatientState, carbs_g: float, bolus_u: float
    ) -> str:
        """Build the AAPS `bolusCalculatorResult` JSON string. Real
        AAPS sends a JSON-stringified blob from the Bolus Wizard
        capturing the inputs at calc time (target BG, ISF, ICR, IoB,
        carbs, etc.). Our translator preserves it verbatim into
        `metadata_json.bolus_calculator_result` for downstream AI
        analysis, so emit a realistic shape here.

        Returns a JSON-encoded string (not a dict). The caller then
        embeds this string as one field inside the bolus payload,
        which is itself JSON-encoded by `http_post`. Double-encoding
        is intentional: NS stores `bolusCalculatorResult` as a string
        on the wire (real AAPS does the same)."""
        return json.dumps(
            {
                "targetBGLow": TARGET_BG_MGDL - 10,
                "targetBGHigh": TARGET_BG_MGDL + 10,
                "isf": ISF_MGDL_PER_UNIT,
                "ic": ICR_GRAMS_PER_UNIT,
                "iob": round(state.iob, 2),
                "bg": int(round(state.bg)),
                "carbs": round(carbs_g, 1),
                "bolusIOB": round(bolus_u, 2),
                "calculatedTotalInsulin": round(bolus_u, 2),
                "carbsEquivalent": round(carbs_g, 1),
            }
        )

    def _post_treatment(
        self, body: dict, *, posted_at: datetime.datetime
    ) -> None:
        """V1 path: array body to /api/v1/treatments.json + api-secret.
        V3 overrides to POST single doc to /api/v3/treatments + JWT
        + a v3 overlay (identifier, mills, utcOffset, isReadOnly,
        isValid). The `posted_at` arg is unused here but the v3 lens
        needs it to derive `mills` / `date` for the overlay -- pass it
        through unconditionally so v3 doesn't have to re-parse
        `created_at`."""
        del posted_at  # v1 doesn't need it
        http_post(
            self.base_url, "/api/v1/treatments.json", self._auth_headers, [body]
        )

    def post_meal_bolus(
        self,
        state: PatientState,
        carbs_g: float,
        bolus_u: float,
        posted_at: datetime.datetime,
    ) -> None:
        # AAPS Meal Bolus shape varies in real fixtures: some records
        # carry both `carbs` and `insulin`, others are carbs-only
        # (announced meal, with the bolus following separately as
        # Correction Bolus or SMB), others are insulin-only. We
        # always bundle both so the GlycemicGPT translator's
        # `meal_bolus_pair` semantic kind fires and creates the
        # linked bolus + carb_entry pump_events. Other AAPS shapes
        # are exercisable by editing this method or by future
        # snack-only / extended-meal lens variants.
        body = {
            "eventType": "Meal Bolus",
            "created_at": iso_z(posted_at),
            "enteredBy": self.device_label,
            "device": self.device_label,
            "insulin": bolus_u,
            "carbs": round(carbs_g, 1),
            "type": "NORMAL",
            "isSMB": False,
            "isBasalInsulin": False,
            "insulinType": AAPS_INSULIN_TYPE,
            "bolusCalculatorResult": self._bolus_calculator_result(
                state, carbs_g, bolus_u
            ),
            **self._aaps_pump_dedup_fields(),
        }
        self._post_treatment(body, posted_at=posted_at)

    def post_correction_bolus(
        self,
        state: PatientState,
        units: float,
        posted_at: datetime.datetime,
    ) -> None:
        # AAPS modeled split: ~80% of corrections fire automatically
        # as `eventType: "SMB"` (the OpenAPSSMB algorithm is the
        # modern default), ~20% as manual `eventType: "Correction
        # Bolus"` (user opens AAPS UI and bolus-corrects manually).
        # Real-world fixture survey: 79 SMB vs 3 Correction Bolus =
        # 96% / 4% split for that user; ours is more generous so a
        # short emulator run still produces both shapes.
        is_manual = self._rng.random() < 0.20
        if is_manual:
            body = {
                "eventType": "Correction Bolus",
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "device": self.device_label,
                "insulin": units,
                "type": "NORMAL",
                "isSMB": False,
                "isBasalInsulin": False,
                "insulinType": AAPS_INSULIN_TYPE,
                "bolusCalculatorResult": self._bolus_calculator_result(
                    state, 0.0, units
                ),
                **self._aaps_pump_dedup_fields(),
            }
        else:
            body = {
                "eventType": "SMB",
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "device": self.device_label,
                "insulin": units,
                "automatic": True,
                "type": "SMB",
                "isSMB": True,
                "isBasalInsulin": False,
                "insulinType": AAPS_INSULIN_TYPE,
                **self._aaps_pump_dedup_fields(),
            }
        self._post_treatment(body, posted_at=posted_at)

    def post_temp_basal(
        self,
        state: PatientState,
        rate_u_hr: float,
        duration_min: int,
        posted_at: datetime.datetime,
    ) -> None:
        # AAPS posts `duration` in MINUTES on Temp Basal treatments
        # (Loop posts the same field in seconds). Real AAPS does this
        # every loop cycle in absolute mode IFF the user has "Upload
        # temp basals" enabled in NSClient -- most users have it OFF
        # to save NS quota. Survey of one user's 133 treatments
        # showed zero Temp Basal records. Default to OFF; opt in via
        # `NS_AAPS_UPLOAD_TEMP_BASALS=true` when the contributor
        # wants exhaustive temp_basal mapper coverage. The `type`
        # field carries the AAPS subtype (NORMAL /
        # EMULATED_PUMP_SUSPEND / PUMP_SUSPEND) which our translator
        # preserves into `metadata_json.aaps_type`.
        if not self._upload_temp_basals:
            return
        delivered = round(rate_u_hr * (duration_min / 60.0), 3)
        body = {
            "eventType": "Temp Basal",
            "created_at": iso_z(posted_at),
            "enteredBy": self.device_label,
            "device": self.device_label,
            "rate": rate_u_hr,
            "absolute": rate_u_hr,
            "duration": duration_min,  # MINUTES, not seconds
            "amount": delivered,
            "automatic": True,
            "type": "NORMAL",
            "insulinType": AAPS_INSULIN_TYPE,
            **self._aaps_pump_dedup_fields(),
        }
        self._post_treatment(body, posted_at=posted_at)

    # ---- per-day events (Profile Switch, Temporary Target) -------------

    def _post_temp_target(
        self,
        posted_at: datetime.datetime,
        *,
        target_mgdl: int,
        duration_min: int,
        reason: str = "Exercise",
    ) -> None:
        """Real AAPS users set Temporary Targets for exercise (raise
        target to e.g. 140 mg/dL), low-glucose recovery (raise to
        140), or sleep (sometimes lower). Translator handles via
        `_map_temp_target` -> PumpEventType.TEMP_TARGET."""
        body = {
            "eventType": "Temporary Target",
            "created_at": iso_z(posted_at),
            "enteredBy": self.device_label,
            "device": self.device_label,
            "targetTop": target_mgdl,
            "targetBottom": target_mgdl - 10,
            "duration": duration_min,
            "reason": reason,
            "units": "mg/dl",
        }
        self._post_treatment(body, posted_at=posted_at)

    def _post_profile_switch(
        self,
        posted_at: datetime.datetime,
        *,
        profile: str,
        percentage: int,
        duration_min: int,
        timeshift: int = 0,
    ) -> None:
        """Real AAPS Profile Switch carries a `percentage` adjustment
        (130% = +30% basal/bolus, useful for sick days), an optional
        `timeshift` (DST / travel adjustment), and a `duration` in
        minutes (0 = indefinite). Translator handles via
        `_map_profile_switch` -> PumpEventType.PROFILE_SWITCH."""
        body = {
            "eventType": "Profile Switch",
            "created_at": iso_z(posted_at),
            "enteredBy": self.device_label,
            "device": self.device_label,
            "profile": profile,
            "percentage": percentage,
            "timeshift": timeshift,
            "duration": duration_min,
        }
        self._post_treatment(body, posted_at=posted_at)

    def post_site_change(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        # AAPS uses `Site Change` for cannula change; the upstream
        # spec at mapping/aaps/nsclient-schema.md says the eventType
        # enum value is CANNULA_CHANGE -> "Site Change".
        # NOTE: per `nsclient-schema.md`, `identifier` is server-
        # assigned; AAPS clients don't include it on POST. We
        # follow that convention and let NS assign `_id`.
        body = {
            "eventType": "Site Change",
            "created_at": iso_z(posted_at),
            "enteredBy": self.device_label,
            "device": self.device_label,
            "notes": "Cannula change (emulated)",
        }
        self._post_treatment(body, posted_at=posted_at)


# ---------------------------------------------------------------------------
# AAPS NSClientV3 lens (Nightscout API v3 + JWT)
# ---------------------------------------------------------------------------
#
# Anchor: the two AAPS NSClient sync paths -- legacy (NSClientV1, this
# emulator's `aaps_v1`) and modern (NSClientV3) -- share the same
# treatment / devicestatus / entry SHAPES, but differ in auth and
# transport:
#
#   - **Auth**: legacy posts the SHA-1 of the API_SECRET in an
#     `api-secret` header against `/api/v1/*.json` paths. NSClientV3
#     instead obtains a JWT from `/api/v2/authorization/request/<token>`
#     where `<token>` is a NS subject access token, and sends it as
#     `Authorization: Bearer <jwt>` against `/api/v3/*` paths.
#
#   - **Transport**: v3 endpoints accept ONE document per POST (not an
#     array) and require a client-generated UUID `identifier` per
#     record, which becomes the resource ID. The server populates
#     `srvCreated` / `srvModified` on each record and uses
#     `srvModified` for incremental sync via `lastModified` query
#     params. The client also stamps `mills` (epoch ms) alongside
#     `date`, plus an integer `utcOffset` and the immutability /
#     soft-delete flags `isReadOnly` and `isValid`.
#
# Verified against the running NS test stack (15.0.8, apiVersion 3.0.5):
# v3-posted records ARE visible via the `/api/v1/*.json` GET endpoints
# (with their v3 fields preserved -- `identifier`, `srvCreated`,
# `srvModified`, `subject`, `mills`), so the GlycemicGPT translator
# (which currently only fetches v1) reads them transparently. That
# means this lens drives the same translator code paths the v1 lens
# does, but additionally exercises the v3 wire format end-to-end.
#
# Source-of-truth files cross-checked:
#   - `mapping/aaps/nightscout-sync.md` (NSClientV3 vs legacy split)
#   - `mapping/aaps/nsclient-schema.md` (treatment / devicestatus
#     fields shared with v1, plus v3-only `srvCreated` /
#     `srvModified` / `subject` / `modifiedBy` / `isReadOnly`)
#   - cgm-remote-monitor `lib/authorization/storage.js` (subject
#     accessToken digest format -- NS rewrites the accessToken on
#     subject create to `<abbrev_name>-<digest_first16>`, so the
#     lens reads back the rewritten value rather than trusting the
#     value it sent)
#   - cgm-remote-monitor `lib/authorization/endpoints.js` (the
#     POST `/api/v2/authorization/subjects` endpoint accepts the
#     api-secret SHA-1 header for admin auth, which we use to
#     bootstrap our subject)


AAPS_V3_DEVICE_LABEL = "openaps://AndroidAPS-NSClientV3"
AAPS_V3_SUBJECT_NAME = "aaps-v3-emulator"
# How many seconds before JWT expiry we proactively refresh. The NS
# server-issued JWT has ~8h lifetime; refreshing 60s early gives us
# slack against clock skew between dev box and NS container.
AAPS_V3_JWT_REFRESH_BUFFER_SECONDS = 60


class AapsV3Lens(AapsV1Lens):
    """AAPS NSClientV3 lens. See architecture comment block above for
    the full v1-vs-v3 wire-format diff. This class reuses every
    AAPS-specific BODY shape (entries, devicestatus, all treatment
    types, profile) from `AapsV1Lens` -- those are identical between
    the two NSClient sync modes. The only overrides are the post
    helpers (different endpoint + auth + envelope) and the auth
    lifecycle (subject bootstrap, JWT acquisition + refresh)."""

    name = "aaps_v3"

    def __init__(
        self, base_url: str, api_secret: str, device_label: str | None = None
    ) -> None:
        super().__init__(base_url, api_secret, device_label)
        # NSClientV3 subjects are bootstrapped lazily on the first
        # call that needs auth, not in __init__. That keeps unit-test
        # construction (no NS reachable) cheap and keeps the
        # constructor side-effect-free, matching v1's __init__.
        self._v3_access_token: str | None = None
        self._v3_jwt: str | None = None
        self._v3_jwt_exp_epoch: int = 0

    @classmethod
    def default_device_label(cls) -> str:
        # Distinct from `aaps_v1`'s label so a single NS instance can
        # carry both lens runs in parallel without their devicestatus
        # rows colliding -- the NSClient v3 vs v1 split is a per-
        # uploader-app decision, so a real user runs ONE of them, not
        # both. The translator keys pump_events by `source +
        # device_label`, so distinct labels keep them in distinct
        # buckets even on the same connection.
        return AAPS_V3_DEVICE_LABEL

    # ---- v3 auth lifecycle ---------------------------------------------

    def _bootstrap_v3_subject(self) -> str:
        """Idempotently ensure a NS subject named AAPS_V3_SUBJECT_NAME
        exists, return its accessToken. Authenticated to the NS admin
        side via the api-secret SHA-1 header.

        Subjects in NS are created with a name + role list; NS REWRITES
        the accessToken to `<abbrev_name>-<digest_first16>` on insert.
        Any token the client sends is discarded. So we POST to create
        (or skip if a subject by this name already exists), then GET
        the list back to pick up the NS-assigned accessToken.

        We require the `admin` role so the same subject can manage
        records across all collections. A real AAPS user typically
        configures a more restricted subject (e.g., careportal +
        devicestatus-upload), but this is a dev fixture: minimum
        viable permissions would just add subject-management noise
        per collection.
        """
        list_path = "/api/v2/authorization/subjects"
        existing = http_get(self.base_url, list_path, self._auth_headers)
        if isinstance(existing, list):
            for subject in existing:
                if (
                    isinstance(subject, dict)
                    and subject.get("name") == AAPS_V3_SUBJECT_NAME
                ):
                    token = subject.get("accessToken")
                    if isinstance(token, str) and token:
                        return token

        # Create. The placeholder accessToken is overwritten by NS;
        # we don't trust the value we sent, only the value we read
        # back below. Tolerate HTTPError from the create call -- if a
        # sibling emulator instance raced us and won, NS may reject
        # the duplicate name; the re-list below still finds the
        # subject either way.
        create_payload = {
            "name": AAPS_V3_SUBJECT_NAME,
            "accessToken": "placeholder-rewritten-by-ns",
            "roles": ["admin"],
            "notes": "Auto-created by GlycemicGPT ns_emulator AAPS v3 lens.",
        }
        try:
            http_post(
                self.base_url, list_path, self._auth_headers, create_payload
            )
        except urllib.error.HTTPError as exc:
            # Re-raise on 401/403 (auth misconfig is fail-loud) but
            # otherwise fall through to the re-list, which will find
            # the subject if a concurrent caller created it.
            if exc.code in (401, 403):
                raise
        # Re-list to pick up the NS-assigned accessToken.
        listed = http_get(self.base_url, list_path, self._auth_headers)
        if isinstance(listed, list):
            for subject in listed:
                if (
                    isinstance(subject, dict)
                    and subject.get("name") == AAPS_V3_SUBJECT_NAME
                ):
                    token = subject.get("accessToken")
                    if isinstance(token, str) and token:
                        return token
        raise RuntimeError(
            "ns_emulator aaps_v3: created subject but could not read it back; "
            "check NS auth + admin permissions."
        )

    def _refresh_v3_jwt(self) -> None:
        """Acquire (or re-acquire) a JWT from NS using the cached
        access token. Called lazily by `_v3_headers` when the cached
        JWT is missing or near expiry.

        NS returns `{"token": "<jwt>", "iat": ..., "exp": ...}`
        where `exp` is the JWT expiry (epoch seconds, NS issues an
        ~8 hour TTL). We honor that as a hard ceiling -- refresh
        slightly before to absorb dev-box-to-NS-container clock
        skew."""
        if self._v3_access_token is None:
            self._v3_access_token = self._bootstrap_v3_subject()
        path = f"/api/v2/authorization/request/{self._v3_access_token}"
        result = http_get(self.base_url, path, {})  # unauthenticated path
        # Don't include the parsed result in the exception message --
        # if NS ever returned an unexpected body that nonetheless
        # contained a token field, the message would leak through
        # the main loop's error logging.
        if not isinstance(result, dict):
            raise RuntimeError(
                "ns_emulator aaps_v3: unexpected JWT response shape "
                f"(type={type(result).__name__})"
            )
        token = result.get("token")
        exp = result.get("exp")
        if not isinstance(token, str) or not isinstance(exp, int):
            raise RuntimeError(
                "ns_emulator aaps_v3: malformed JWT response "
                "(missing/invalid token or exp field)"
            )
        self._v3_jwt = token
        self._v3_jwt_exp_epoch = int(exp)

    def _v3_headers(self) -> dict[str, str]:
        """Return Bearer auth header, refreshing the JWT if needed."""
        now = int(time.time())
        if (
            self._v3_jwt is None
            or now >= self._v3_jwt_exp_epoch - AAPS_V3_JWT_REFRESH_BUFFER_SECONDS
        ):
            self._refresh_v3_jwt()
        return {"Authorization": f"Bearer {self._v3_jwt}"}

    # ---- v3 transport overlay ------------------------------------------

    def _v3_overlay(self, posted_at: datetime.datetime) -> dict:
        """Return v3-only fields the NS API v3 endpoints expect on
        every record: a client-generated UUID identifier, dual
        date/mills epoch-ms timestamps, integer utcOffset (minutes),
        and the immutability / soft-delete flags. Also include `app`
        -- NS API v3 enforces it on every record (`Bad or missing app
        field` 400 otherwise), whereas v1 only requires it on
        entries. The v1 entry builder already sets `app=AAPS` so
        body wins for entries; for devicestatus / treatments / profile
        the overlay value applies.

        NS-side timestamps (`srvCreated`, `srvModified`, `subject`)
        are server-assigned and intentionally NOT set here -- NS sets
        them on insert."""
        date_ms = int(posted_at.timestamp() * 1000)
        return {
            "identifier": str(uuid.uuid4()),
            "date": date_ms,
            "mills": date_ms,
            "utcOffset": 0,
            "isReadOnly": False,
            "isValid": True,
            "app": "AAPS",
        }

    def _post_v3_doc(
        self, collection: str, body: dict, posted_at: datetime.datetime
    ) -> None:
        """Compose v3 doc = body | overlay, POST to /api/v3/<collection>
        with Bearer JWT.

        Order matters: overlay first, body last, so any field present
        in both (`date`, `app`) takes the body's value -- the AAPS
        body builders already set `date` correctly via
        `posted_at.timestamp() * 1000`, but if a future caller passes
        a body with a richer `date` (e.g. milliseconds plus tz adjust),
        we want it to win."""
        merged = {**self._v3_overlay(posted_at), **body}
        http_post(
            self.base_url, f"/api/v3/{collection}", self._v3_headers(), merged
        )

    # ---- v3 post-helper overrides --------------------------------------
    #
    # Each override consumes a body built by the v1 lens (unchanged
    # AAPS payload shape) and routes it to the v3 endpoint with the
    # v3 overlay. The body builders themselves don't need to know
    # which transport they're feeding.

    def _post_entry(
        self, body: dict, *, posted_at: datetime.datetime
    ) -> None:
        self._post_v3_doc("entries", body, posted_at)

    def _post_devicestatus(
        self, body: dict, *, posted_at: datetime.datetime
    ) -> None:
        self._post_v3_doc("devicestatus", body, posted_at)

    def _post_treatment(
        self, body: dict, *, posted_at: datetime.datetime
    ) -> None:
        self._post_v3_doc("treatments", body, posted_at)

    def _post_profile(self, body: dict) -> None:
        # Profile docs don't get a per-record `posted_at` from the
        # caller (the v1 `ensure_profile` doesn't track one). Use
        # now() so the v3 overlay's `date` / `mills` are consistent
        # with NS's server-time clock.
        self._post_v3_doc(
            "profile", body, datetime.datetime.now(datetime.UTC)
        )


# ---------------------------------------------------------------------------
# Trio lens (Nightscout API v1 + SHA-1, oref-derived devicestatus)
# ---------------------------------------------------------------------------
#
# Trio is the iOS closed-loop fork of iAPS / FreeAPS X (which itself
# forked from oref0). Its NS upload pipeline is closer to AAPS than
# to Loop -- both speak the oref `openaps.{iob,suggested,enacted}`
# vocabulary -- but the wire details diverge enough that inheriting
# from `AapsV1Lens` would force a wave of "delete-this" overrides.
# This lens inherits from `Lens` directly.
#
# Distinctions from AAPS that this lens handles explicitly:
#
# - **`enteredBy` / `device`**: Trio stamps `enteredBy: "Trio"` on
#   every treatment AND `device: "Trio"` on devicestatus, but does
#   NOT set `device` on individual treatments (AAPS does). No
#   `app` field anywhere -- v1 doesn't require it, and Trio doesn't
#   send one.
#
# - **No pump composite dedup triple**: Trio dedupes on a
#   client-generated UUID `id` per treatment (queryable via
#   `find[id][$eq]=...`) instead of `pumpId`/`pumpType`/`pumpSerial`.
#   We emit the UUID; whether the GlycemicGPT translator uses it is
#   orthogonal.
#
# - **No `bolusCalculatorResult`**: Trio's bolus wizard inputs are
#   not stamped onto the NS treatment (a real diff vs AAPS, where
#   the Bolus Wizard JSON rides along on every meal/correction
#   bolus).
#
# - **Bolus eventType is just `"Bolus"` or `"SMB"`**: per upstream
#   `Trio/Sources/APS/Storage/PumpHistoryStorage.swift`'s
#   `determineBolusEventType`: a dose with `isSMB=true` becomes
#   `"SMB"`, a dose with `isExternal=true` becomes `"External
#   Insulin"`, every other dose becomes `"Bolus"`. The `"Meal
#   Bolus"` / `"Correction Bolus"` / `"Snack Bolus"` enum cases
#   exist for inbound parsing of foreign uploaders' records but are
#   never EMITTED by Trio itself. So this lens posts user-
#   administered boluses (meal AND manual correction alike) as
#   `"Bolus"`, and algorithm-driven SMBs as `"SMB"`. This is a real
#   semantic loss vs AAPS but it's faithful to what Trio sends.
#
# - **Carbs split off into a separate treatment**: Trio uploads
#   carbs as `eventType: "Carb Correction"` records, NEVER bundled
#   into a Meal Bolus. Our lens posts a paired Bolus + Carb
#   Correction (same `created_at`, separate documents).
#
# - **`Carb Correction` carries fat/protein**: Trio supports the
#   FPU (Flexible Portion Unit) macros, so Carb Correction records
#   include `fat` / `protein` Decimals. We emit zeros for fat/
#   protein (no FPU model in our patient state) but include the
#   keys for shape fidelity.
#
# - **devicestatus shape**: `openaps + pump + uploader`, NO
#   `configuration` subtree. `uploader` is a NESTED object
#   Loop-style (Trio's upstream model has
#   `{batteryVoltage?, battery, isCharging?}`), NOT a top-level
#   `uploaderBattery` int (AAPS-style). This emulator only fills
#   the always-present fields (`battery`, `isCharging`); the
#   optional `batteryVoltage` isn't modeled in PatientState and is
#   omitted. `pump` carries `bolusIncrement` (Trio-specific)
#   alongside the usual `clock`, `battery`, `reservoir`, `status`.
#
# - **`enacted.received`**: Trio uses the correctly-spelled
#   `received` key (lowercase, no typo). An older note in the
#   reference repo claimed Trio preserves an AAPS `recieved` typo;
#   upstream `Trio/Sources/Models/Determination.swift` shows
#   `let received: Bool?` with `case received` in CodingKeys. The
#   reference note is stale. Per the repo-wide rule, upstream wins.
#
# - **Determination JSON capitalization**: `IOB`, `COB`, `ISF`,
#   `CR`, `TDD`, `predBGs.{IOB,COB,UAM,ZT}` (capitalized -- exactly
#   the oref0 wire convention).
#
# - **Profile shape**: includes Trio-specific fields
#   (`bundleIdentifier`, `deviceToken`, `isAPNSProduction`,
#   `overridePresets`, `teamID`). We emit minimal-but-valid values
#   so the NS profile insert succeeds.
#
# Source-of-truth files cross-checked:
#   - `Trio/Sources/Models/NightscoutTreatment.swift`
#   - `Trio/Sources/Models/NightscoutStatus.swift`
#   - `Trio/Sources/Models/Determination.swift`
#   - `Model/Helper/PumpEvent+helper.swift` (EventType enum)
#   - `Trio/Sources/APS/Storage/PumpHistoryStorage.swift`
#     (`determineBolusEventType`)
#   - `Trio/Sources/APS/Storage/CarbsStorage.swift` (`getCarbsNotYet`
#     -> NightscoutTreatment(eventType: .nsCarbCorrection))
#   - `Trio/Sources/Services/Network/Nightscout/NightscoutManager.swift`
#     (upload pipelines, throttling)


TRIO_VERSION = "0.7.1"
TRIO_DEVICE_LABEL = "Trio"
TRIO_BOLUS_INCREMENT = 0.05  # Tandem Mobi-style minimum delivery
TRIO_BUNDLE_IDENTIFIER = "com.trio-iaps.Trio.emulator"


class TrioLens(Lens):
    """Trio (oref-derived iOS closed-loop, fork of iAPS / FreeAPS X)
    lens. See architecture comment block above for the v1-vs-Trio
    wire-format diff."""

    name = "trio"

    def __init__(
        self, base_url: str, api_secret: str, device_label: str | None = None
    ) -> None:
        super().__init__(base_url, api_secret, device_label)
        # Once-per-sim-day Temp Target (morning exercise, the only
        # Trio "override-style" event that actually round-trips
        # through Nightscout -- override presets are profile-time,
        # not per-tick treatments).
        self._last_temp_target_date: str | None = None
        # 80/20 SMB-vs-manual correction split, seed-aware so
        # NS_RANDOM_SEED gives reproducible runs end-to-end.
        seed_env = os.environ.get("NS_RANDOM_SEED")
        try:
            self._rng = (
                random.Random(int(seed_env)) if seed_env else random.Random()
            )
        except ValueError:
            self._rng = random.Random()

    @classmethod
    def default_device_label(cls) -> str:
        return TRIO_DEVICE_LABEL  # "Trio"

    # ---- profile --------------------------------------------------------

    def ensure_profile(self) -> None:
        """Trio profile carries iOS-specific fields (bundleIdentifier,
        deviceToken, isAPNSProduction, teamID, overridePresets) that
        AAPS / Loop don't. NS doesn't enforce them, so we emit
        minimal-but-valid placeholders -- a real Trio app would have
        a real APNS device token from Apple Push registration."""
        try:
            existing = http_get(
                self.base_url, "/api/v1/profile.json", self._auth_headers
            )
            if existing:
                return
        except urllib.error.HTTPError:
            pass

        now_iso = iso_z(datetime.datetime.now(datetime.UTC))
        profile_name = "Trio"
        payload = {
            "defaultProfile": profile_name,
            "store": {
                profile_name: {
                    "dia": str(DIA_MINUTES // 60),
                    "carbratio": [{"time": "00:00", "value": ICR_GRAMS_PER_UNIT}],
                    "sens": [{"time": "00:00", "value": ISF_MGDL_PER_UNIT}],
                    "basal": [{"time": "00:00", "value": SCHEDULED_BASAL_U_HR}],
                    "target_low": [{"time": "00:00", "value": TARGET_BG_MGDL - 10}],
                    "target_high": [{"time": "00:00", "value": TARGET_BG_MGDL + 10}],
                    "carbs_hr": "20",
                    "delay": "20",
                    "timezone": "UTC",
                    "units": "mg/dl",
                }
            },
            "startDate": now_iso,
            "mills": int(time.time() * 1000),
            "units": "mg/dl",
            "enteredBy": TRIO_DEVICE_LABEL,
            # Trio-specific iOS-side fields. Nightscout doesn't
            # validate these; a real Trio user has real values.
            "bundleIdentifier": TRIO_BUNDLE_IDENTIFIER,
            "deviceToken": "emulator-no-apns-token",
            "isAPNSProduction": False,
            "teamID": "EMULATOR",
            "overridePresets": [],
        }
        http_post(
            self.base_url, "/api/v1/profile.json", self._auth_headers, [payload]
        )

    # ---- per-tick hook --------------------------------------------------

    def on_tick_start(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """Trio runs the oref-derived determine-basal every 5 sim-min,
        choosing a new temp basal each cycle. Once per sim-day we also
        fire a Temporary Target (morning-exercise scenario) -- the
        only Trio "override-style" event that actually round-trips
        through Nightscout."""
        rate = loop_temp_basal_decision(state)
        state.set_temp_basal(rate, LOOP_TEMP_BASAL_DURATION_MIN)

        date_iso = state.sim_time.date().isoformat()
        hour = state.sim_time.hour
        if 6 <= hour < 7 and self._last_temp_target_date != date_iso:
            self._last_temp_target_date = date_iso
            try:
                self._post_temp_target(
                    posted_at, target_mgdl=140, duration_min=60
                )
            except Exception as exc:  # noqa: BLE001 - keep loop running
                print(
                    f"[emu] trio temp_target post failed: {exc}", flush=True
                )

    # ---- entries --------------------------------------------------------

    def post_entry(
        self,
        state: PatientState,
        prev_bg: float,
        posted_at: datetime.datetime,
    ) -> None:
        # Trio sends entries with `device: "Trio"` (no `app` field on
        # v1; Trio doesn't bother).
        payload = [
            {
                "type": "sgv",
                "sgv": int(round(state.bg)),
                "direction": direction_for(prev_bg, state.bg),
                "date": int(posted_at.timestamp() * 1000),
                "dateString": iso_z(posted_at),
                "device": self.device_label,
            }
        ]
        http_post(
            self.base_url, "/api/v1/entries.json", self._auth_headers, payload
        )

    # ---- devicestatus ---------------------------------------------------

    def _build_predbgs(self, state: PatientState) -> dict[str, list[int]]:
        """oref-style predBGs (same arrays as AAPS produces -- the
        algorithm's parents). 30-min horizon at 5-min steps = 7
        points. Keys are CAPITAL per oref0 wire convention."""
        base = state.predict_glucose(horizon_min=30)
        # UAM (Unannounced-Meal) prediction must NOT be a flat offset
        # of IOB -- the algorithm checks UAM-vs-IOB divergence to
        # decide whether to enable SMBs. When carbs are active
        # (state.cob > 0), UAM trends toward COB; when COB is zero
        # but BG is elevated, UAM should diverge upward to model the
        # "user ate carbs they didn't enter" scenario.
        return {
            "IOB": base,
            "COB": [int(min(BG_CEIL, v + max(0, state.cob * 0.4))) for v in base],
            "UAM": [
                int(min(BG_CEIL, v + max(5, state.cob * 0.5))) for v in base
            ],
            "ZT": [int(min(BG_CEIL, v + max(0, state.iob * 5))) for v in base],
        }

    def post_devicestatus(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        ts = iso_z(posted_at)
        iob_subtree = {
            "iob": round(state.iob, 3),
            "basaliob": round(state.iob * 0.4, 3),
            "bolussnooze": 0.0,
            "activity": round(state.iob * 0.0008, 6),
            "time": ts,
        }
        predicted = self._build_predbgs(state)
        eventual_bg = (
            predicted["IOB"][-1] if predicted["IOB"] else int(round(state.bg))
        )
        # Approximate running TDD from the in-memory bolus history +
        # scheduled basal coverage so far. Real Trio computes a
        # rolling 7-day average; ours is a since-sim-start sum, which
        # is plausible enough for AI consumers that read TDD as a
        # rough magnitude check ("does this user dose ~30U/day or
        # ~70U/day?"). Hours elapsed in sim-time, not wall-time.
        sim_hours_elapsed = max(state.sim_minute / 60.0, 1.0 / 60.0)
        bolus_total = state.total_bolus_units_delivered
        tdd_estimate = bolus_total + SCHEDULED_BASAL_U_HR * sim_hours_elapsed

        # Trio Determination JSON uses CAPITAL keys (IOB / COB /
        # ISF / CR / TDD), exactly the oref0 wire convention. Lower-
        # case `iob` is the local Swift property name; the JSON key
        # is `IOB`. See `Trio/Sources/Models/Determination.swift`
        # CodingKeys.
        cob_r = round(state.cob, 1)
        iob_r = round(state.iob, 2)
        target_i = int(TARGET_BG_MGDL)
        rate_r = state.temp_basal_rate_u_hr
        determination = {
            "reason": (
                f"COB: {cob_r}, IOB: {iob_r}, ISF: {ISF_MGDL_PER_UNIT}, "
                f"CR: {ICR_GRAMS_PER_UNIT}, Target: {target_i}, "
                f"eventualBG: {eventual_bg}, rate: {rate_r}"
            ),
            "temp": "absolute",
            "bg": int(round(state.bg)),
            "eventualBG": eventual_bg,
            "insulinReq": 0.0,
            "sensitivityRatio": 1.0,
            "rate": state.temp_basal_rate_u_hr,
            "duration": LOOP_TEMP_BASAL_DURATION_MIN,
            "predBGs": predicted,
            "IOB": round(state.iob, 3),
            "COB": round(state.cob, 1),
            "ISF": ISF_MGDL_PER_UNIT,
            "CR": ICR_GRAMS_PER_UNIT,
            "TDD": round(tdd_estimate, 2),
            "deliverAt": ts,
            "reservoir": round(state.reservoir_u, 1),
            "current_target": int(TARGET_BG_MGDL),
            # `current_basal` is the scheduled (non-temp) rate at
            # this hour. Upstream `Determination.swift` exposes it
            # alongside the temp `rate`, so AI consumers reading
            # "what would the pump do without the loop?" get a
            # meaningful answer.
            "current_basal": SCHEDULED_BASAL_U_HR,
            "timestamp": ts,
        }
        # `enacted` mirrors `suggested` plus `received: true`.
        # `received` (correctly spelled, lowercase) is the actual
        # upstream Trio key -- see
        # `Trio/Sources/Models/Determination.swift` CodingKeys.
        enacted = {**determination, "received": True}

        # Trio's NSPumpStatus carries `bolusIncrement` (Mobi 0.05U)
        # in addition to the usual fields -- a real diff vs AAPS.
        pump_subtree = {
            "clock": ts,
            "battery": {"percent": int(state.pump_battery_pct)},
            "reservoir": round(state.reservoir_u, 1),
            "status": {"status": "normal", "suspended": state.pump_suspended},
            "bolusIncrement": TRIO_BOLUS_INCREMENT,
        }

        # Trio's Uploader is a NESTED object (Loop-style), NOT a
        # top-level `uploaderBattery` int (AAPS-style). Upstream has
        # `{batteryVoltage?, battery, isCharging?}`. We omit
        # `batteryVoltage` since PatientState doesn't model phone
        # battery voltage; the always-required `battery` (int %) and
        # `isCharging` (bool) cover the dashboard's read paths.
        uploader_subtree = {
            "battery": int(state.phone_battery_pct),
            "isCharging": state.phone_is_charging,
        }

        payload = [
            {
                "device": self.device_label,
                "created_at": ts,
                "openaps": {
                    "iob": iob_subtree,
                    "suggested": determination,
                    "enacted": enacted,
                    "version": TRIO_VERSION,
                },
                "pump": pump_subtree,
                "uploader": uploader_subtree,
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/devicestatus.json",
            self._auth_headers,
            payload,
        )

    # ---- treatments -----------------------------------------------------

    def _new_id(self) -> str:
        """Fresh client-generated UUID for treatment dedupe. Trio
        keys NS treatments by this id (queries via
        `find[id][$eq]=...`)."""
        return str(uuid.uuid4())

    def post_meal_bolus(
        self,
        state: PatientState,
        carbs_g: float,
        bolus_u: float,
        posted_at: datetime.datetime,
    ) -> None:
        """Trio uploads meals as TWO separate treatments at the same
        `created_at`: one `Carb Correction` (carbs only, with FPU
        macros) and one `Bolus` (insulin only). The user-side bolus
        wizard combined them; the upload pipeline splits them.

        Per upstream `PumpHistoryStorage.determineBolusEventType`,
        a non-SMB user-administered bolus is `eventType: "Bolus"`
        regardless of whether it covered a meal or a correction.
        Trio simply doesn't distinguish meal-bolus vs. correction-
        bolus on the wire. So we post `"Bolus"` here, NOT `"Meal
        Bolus"` (the latter is in the EventType enum but only
        appears when Trio ingests other apps' records). See class
        docstring for the full upstream-vs-Ben's-notes reconciliation.
        """
        created_at = iso_z(posted_at)
        carb_payload = [
            {
                "eventType": "Carb Correction",
                "created_at": created_at,
                "enteredBy": self.device_label,
                "carbs": round(carbs_g, 1),
                "fat": 0,
                "protein": 0,
                "id": self._new_id(),
            }
        ]
        bolus_payload = [
            {
                "eventType": "Bolus",
                "created_at": created_at,
                "enteredBy": self.device_label,
                "insulin": bolus_u,
                "id": self._new_id(),
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            carb_payload,
        )
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            bolus_payload,
        )

    def post_correction_bolus(
        self,
        state: PatientState,
        units: float,
        posted_at: datetime.datetime,
    ) -> None:
        """Trio split: ~80% of corrections fire automatically as
        `eventType: "SMB"` (the SMB algorithm is the modern Trio
        default), ~20% as user-initiated `eventType: "Bolus"`
        (manual correction via the in-app bolus wizard). Note that
        Trio does NOT use `eventType: "Correction Bolus"` on
        upload -- see class docstring."""
        is_manual = self._rng.random() < 0.20
        if is_manual:
            payload = [
                {
                    "eventType": "Bolus",
                    "created_at": iso_z(posted_at),
                    "enteredBy": self.device_label,
                    "insulin": units,
                    "id": self._new_id(),
                }
            ]
        else:
            payload = [
                {
                    "eventType": "SMB",
                    "created_at": iso_z(posted_at),
                    "enteredBy": self.device_label,
                    "insulin": units,
                    "id": self._new_id(),
                }
            ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )

    def post_temp_basal(
        self,
        state: PatientState,
        rate_u_hr: float,
        duration_min: int,
        posted_at: datetime.datetime,
    ) -> None:
        """Trio always uploads temp basals (no NSClient-style 'Upload
        temp basals' opt-out toggle). Real Trio users see every loop
        cycle's temp-basal decision in their NS treatments tab."""
        payload = [
            {
                "eventType": "Temp Basal",
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "rate": rate_u_hr,
                "absolute": rate_u_hr,
                "duration": duration_min,
                "id": self._new_id(),
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )

    def post_site_change(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """Trio's `EventType.nsSiteChange` -> "Site Change". On Trio
        this fires from the pump-history `prime` event (CGM/pod
        replacement) -- we trigger from the shared physiology engine
        when the reservoir hits the refill threshold."""
        payload = [
            {
                "eventType": "Site Change",
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "id": self._new_id(),
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )

    # ---- private: temp target ------------------------------------------

    def _post_temp_target(
        self,
        posted_at: datetime.datetime,
        *,
        target_mgdl: int,
        duration_min: int,
        reason: str = "Exercise",
    ) -> None:
        """Real Trio users set Temporary Targets for exercise (raise
        target to e.g. 140 mg/dL), low-glucose recovery, or sleep.
        The full Override (percentage / ISF-CR scaling / SMB-disable)
        state is stored locally in CoreData and -- per current Trio
        upload code -- DOES surface in the profile's
        `overridePresets`, but not as per-event treatments. So this
        Temp Target is the only Trio override-style event we emit on
        the treatments timeline."""
        payload = [
            {
                "eventType": "Temporary Target",
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "targetTop": target_mgdl,
                "targetBottom": target_mgdl - 10,
                "duration": duration_min,
                "reason": reason,
                "units": "mg/dl",
                "id": self._new_id(),
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )


# ---------------------------------------------------------------------------
# oref0 lens (the original OpenAPS, Raspberry Pi command-line)
# ---------------------------------------------------------------------------
#
# oref0 is the reference implementation that AAPS, iAPS, FreeAPS X, and
# Trio all forked from. It runs on a Raspberry Pi as a Linux command-line
# system (NOT iOS, NOT Android) and uploads to Nightscout via a shell
# script (`bin/oref0-ns-loop.sh`) that calls into Node helpers
# (`bin/ns-status.js`).
#
# oref0 is the SIMPLEST oref-family wire format. Its descendants added
# fields; oref0 itself emits the bare original shape:
#
# - **Identity**: TWO different URI shapes on the same upload pipeline:
#   * devicestatus: `device: "openaps://" + os.hostname()` -- scheme
#     and hostname only, no path component. Per upstream
#     `bin/ns-status.js`.
#   * treatments: `enteredBy: "openaps://medtronic/<model>"` -- adds
#     a `/<model>` path component. Per upstream
#     `bin/mm-format-ns-treatments.sh`. The reference repo's claim
#     of bare `"openaps"` enteredBy turned out to be stale; upstream's
#     algorithm-driven pipeline uses the URI form. Care Portal manual
#     entries on real oref0 boxes can have blank or bare `"openaps"`,
#     but the Nightscout-via-pump-history pipeline (which is what
#     this lens models) uses the URI form.
#   * Note: the GlycemicGPT translator's `parse_openaps_uri` requires
#     a non-empty path component to classify as oref0; the bare
#     `openaps://hostname` form (no path) gets classified as `aaps`.
#     Real oref0 deployments hit this same translator-side limitation
#     in production. No functional impact since no code paths branch
#     on `uploader == "oref0"`.
#
# - **No client-side dedupe**: no `id` UUID, no `pumpId` / `pumpType` /
#   `pumpSerial` triple. Relies entirely on Nightscout's server-side
#   `_id` allocation and `created_at + eventType`-based dedupe at the
#   API layer.
#
# - **Bolus eventType preserves the Meal/Correction distinction**:
#   `"Meal Bolus"`, `"Correction Bolus"`, and `"SMB"` are all distinct
#   on the wire (Trio collapsed Meal/Correction into a generic `"Bolus"`
#   on its upload code path; oref0 keeps them separate).
#
# - **Carb / FPU support is glucose-only**: no `fat` / `protein` macros
#   on Carb Correction records — that's a Trio (FPU) extension. oref0
#   ships only `carbs`.
#
# - **`pump` subtree is leaner than Trio's**: `clock`, `battery`,
#   `reservoir`, `status` only. No `bolusIncrement` (Trio-specific).
#   Battery may be either an int or an object depending on pump driver.
#
# - **`uploader` shape defaults to AAPS-style top-level int**: in
#   `bin/ns-status.js`, when the uploader_input is a number, it
#   serializes as `{ battery: <int> }` nested OR as a top-level
#   `uploaderBattery` field depending on the helper invocation. We
#   emit the top-level int (most-common in real oref0 deployments).
#
# - **Determination JSON capitalization** matches the oref-family
#   convention: `IOB`, `COB`, `ISF`, `CR`, `TDD`, `predBGs.{IOB,COB,
#   UAM,ZT}` all CAPITAL. `received` (correctly spelled, lowercase)
#   in `enacted`.
#
# - **No iOS-specific profile fields**: no `bundleIdentifier`, no
#   `deviceToken`, no `isAPNSProduction`, no `teamID`, no
#   `overridePresets`. Just the standard NS profile shape (defaultProfile,
#   store, startDate, mills, units).
#
# Source-of-truth files cross-checked:
#   - `mapping/oref0/data-models.md` (treatment + devicestatus shapes)
#   - upstream `openaps/oref0:bin/ns-status.js` (devicestatus payload)
#   - upstream `openaps/oref0:lib/bolus.js` (eventType assignment)
#   - upstream `openaps/oref0:examples/suggested.json` (Determination shape)
#   - upstream `openaps/oref0:bin/oref0-ns-loop.sh` (carb upload flow)


OREF0_VERSION = "0.7.0"
# Default hostname is fixed (`"openaps-emulator"`) so devicestatus
# records are run-to-run reproducible: under a fixed `NS_RANDOM_SEED`
# every `device` field is identical, which makes diffs between
# emulator runs review-friendly. Real oref0 boxes use
# `socket.gethostname()`. Set `NS_OREF0_HOSTNAME` to override (e.g.,
# to your actual Pi's hostname when stress-testing the translator's
# `parse_openaps_uri` heuristic against varied real-world inputs).
OREF0_HOSTNAME = os.environ.get("NS_OREF0_HOSTNAME", "openaps-emulator")
# `device` on devicestatus: `"openaps://<hostname>"` -- scheme and
# hostname only, NO path component. Per upstream
# `openaps/oref0:bin/ns-status.js`:
#   `device: 'openaps://' + os.hostname(),`
# Note: the GlycemicGPT translator's `detect_uploader` (in
# `apps/api/src/services/integrations/nightscout/models.py`) requires
# a non-empty path component to classify as oref0; the bare
# `openaps://hostname` form (no path) gets classified as `aaps`. Real
# oref0 deployments hit this same misclassification in production.
# That's a translator-side limitation, not a lens defect -- per the
# repo rule, upstream wins. Treatments separately use the
# `openaps://<driver>/<model>` form below, which DOES classify
# correctly.
OREF0_DEVICE_LABEL = f"openaps://{OREF0_HOSTNAME}"
# `enteredBy` on treatments uses the URI form
# `"openaps://<pump-driver>/<model>"` (scheme + hostname + a
# `/<model>` path component), per upstream
# `openaps/oref0:bin/mm-format-ns-treatments.sh`:
#   `.enteredBy = "openaps://medtronic/'$model'"`
# Modeled patient runs an older Medtronic 722 (a popular oref0 box;
# pre-encryption Medtronic + Carelink stick = canonical oref0 setup
# from 2015-2018). The translator parses this form to
# `(host="medtronic", ref="722")` and classifies as oref0 correctly.
# Note: Care Portal manual entries on real oref0 boxes would have
# blank or `"openaps"` literal `enteredBy`; this lens uses only the
# URI form for consistency.
OREF0_PUMP_DRIVER = "medtronic"
OREF0_PUMP_MODEL = "722"
OREF0_ENTERED_BY = f"openaps://{OREF0_PUMP_DRIVER}/{OREF0_PUMP_MODEL}"


class Oref0Lens(Lens):
    """oref0 (original OpenAPS) lens. See architecture comment block
    above for the full vs-Trio / vs-AAPS wire-format diff."""

    name = "oref0"

    def __init__(
        self, base_url: str, api_secret: str, device_label: str | None = None
    ) -> None:
        super().__init__(base_url, api_secret, device_label)
        # Once-per-sim-day Temp Target (oref0 reads NS-side TempTargets
        # on every loop tick to influence its target_bg in
        # determine-basal). Real oref0 users set Temporary Targets via
        # the Nightscout Care Portal during exercise / sleep / sick days.
        self._last_temp_target_date: str | None = None
        # 80/20 SMB-vs-manual correction split, seed-aware.
        seed_env = os.environ.get("NS_RANDOM_SEED")
        try:
            self._rng = (
                random.Random(int(seed_env)) if seed_env else random.Random()
            )
        except ValueError:
            self._rng = random.Random()

    @classmethod
    def default_device_label(cls) -> str:
        return OREF0_DEVICE_LABEL

    # ---- profile --------------------------------------------------------

    def ensure_profile(self) -> None:
        """oref0 profile is the bare standard NS profile shape -- no
        iOS-specific fields like Trio's bundleIdentifier / deviceToken /
        teamID / overridePresets, and no AAPS-specific keys. Real
        oref0 users typically set their profile via Nightscout's web
        UI or via `oref0-set-up-ns-profile`; the upload itself is
        the same standard shape."""
        try:
            existing = http_get(
                self.base_url, "/api/v1/profile.json", self._auth_headers
            )
            if existing:
                return
        except urllib.error.HTTPError:
            pass

        now_iso = iso_z(datetime.datetime.now(datetime.UTC))
        profile_name = "openaps"
        payload = {
            "defaultProfile": profile_name,
            "store": {
                profile_name: {
                    "dia": str(DIA_MINUTES // 60),
                    "carbratio": [{"time": "00:00", "value": ICR_GRAMS_PER_UNIT}],
                    "sens": [{"time": "00:00", "value": ISF_MGDL_PER_UNIT}],
                    "basal": [{"time": "00:00", "value": SCHEDULED_BASAL_U_HR}],
                    "target_low": [{"time": "00:00", "value": TARGET_BG_MGDL - 10}],
                    "target_high": [{"time": "00:00", "value": TARGET_BG_MGDL + 10}],
                    "carbs_hr": "20",
                    "delay": "20",
                    "timezone": "UTC",
                    "units": "mg/dl",
                }
            },
            "startDate": now_iso,
            "mills": int(time.time() * 1000),
            "units": "mg/dl",
            "enteredBy": OREF0_ENTERED_BY,
        }
        http_post(
            self.base_url, "/api/v1/profile.json", self._auth_headers, [payload]
        )

    # ---- per-tick hook --------------------------------------------------

    def on_tick_start(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """oref0's main loop runs determine-basal every 5 sim-min via
        cron / oref0-ns-loop.sh, choosing a new temp basal each cycle.
        Once per sim-day we also fire a Temporary Target -- real
        oref0 users set TempTargets via the Nightscout Care Portal
        during exercise / sleep / sick days, and oref0 reads them on
        the next loop cycle to bias its target."""
        rate = loop_temp_basal_decision(state)
        state.set_temp_basal(rate, LOOP_TEMP_BASAL_DURATION_MIN)

        date_iso = state.sim_time.date().isoformat()
        hour = state.sim_time.hour
        if 6 <= hour < 7 and self._last_temp_target_date != date_iso:
            self._last_temp_target_date = date_iso
            try:
                self._post_temp_target(
                    posted_at, target_mgdl=140, duration_min=60
                )
            except Exception as exc:  # noqa: BLE001 - keep loop running
                print(
                    f"[emu] oref0 temp_target post failed: {exc}", flush=True
                )

    # ---- entries --------------------------------------------------------

    def post_entry(
        self,
        state: PatientState,
        prev_bg: float,
        posted_at: datetime.datetime,
    ) -> None:
        # oref0 entries: minimal sgv shape, `device` carries the full
        # `openaps://hostname` form. No `app` field; oref0 doesn't
        # set one.
        payload = [
            {
                "type": "sgv",
                "sgv": int(round(state.bg)),
                "direction": direction_for(prev_bg, state.bg),
                "date": int(posted_at.timestamp() * 1000),
                "dateString": iso_z(posted_at),
                "device": self.device_label,
            }
        ]
        http_post(
            self.base_url, "/api/v1/entries.json", self._auth_headers, payload
        )

    # ---- devicestatus ---------------------------------------------------

    def _build_predbgs(self, state: PatientState) -> dict[str, list[int]]:
        """oref-style predBGs (4 arrays at 5-min steps, 30-min horizon).
        Same convention as the descendants -- oref0 was the original
        emitter of this shape."""
        base = state.predict_glucose(horizon_min=30)
        return {
            "IOB": base,
            "COB": [int(min(BG_CEIL, v + max(0, state.cob * 0.4))) for v in base],
            "UAM": [
                int(min(BG_CEIL, v + max(5, state.cob * 0.5))) for v in base
            ],
            "ZT": [int(min(BG_CEIL, v + max(0, state.iob * 5))) for v in base],
        }

    def post_devicestatus(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        ts = iso_z(posted_at)
        iob_subtree = {
            "iob": round(state.iob, 3),
            "basaliob": round(state.iob * 0.4, 3),
            "bolussnooze": 0.0,
            "activity": round(state.iob * 0.0008, 6),
            "time": ts,
        }
        predicted = self._build_predbgs(state)
        eventual_bg = (
            predicted["IOB"][-1] if predicted["IOB"] else int(round(state.bg))
        )
        sim_hours_elapsed = max(state.sim_minute / 60.0, 1.0 / 60.0)
        bolus_total = state.total_bolus_units_delivered
        tdd_estimate = bolus_total + SCHEDULED_BASAL_U_HR * sim_hours_elapsed

        cob_r = round(state.cob, 1)
        iob_r = round(state.iob, 2)
        target_i = int(TARGET_BG_MGDL)
        rate_r = state.temp_basal_rate_u_hr
        # Determination uses CAPITAL keys -- the canonical oref-wire
        # convention. AAPS and Trio inherited this from oref0.
        determination = {
            "reason": (
                f"COB: {cob_r}, IOB: {iob_r}, ISF: {ISF_MGDL_PER_UNIT}, "
                f"CR: {ICR_GRAMS_PER_UNIT}, Target: {target_i}, "
                f"eventualBG: {eventual_bg}, rate: {rate_r}"
            ),
            "temp": "absolute",
            "bg": int(round(state.bg)),
            "eventualBG": eventual_bg,
            "insulinReq": 0.0,
            "sensitivityRatio": 1.0,
            "rate": state.temp_basal_rate_u_hr,
            "duration": LOOP_TEMP_BASAL_DURATION_MIN,
            "predBGs": predicted,
            "IOB": round(state.iob, 3),
            "COB": round(state.cob, 1),
            "ISF": ISF_MGDL_PER_UNIT,
            "CR": ICR_GRAMS_PER_UNIT,
            "TDD": round(tdd_estimate, 2),
            "deliverAt": ts,
            "reservoir": round(state.reservoir_u, 1),
            "current_target": int(TARGET_BG_MGDL),
            "current_basal": SCHEDULED_BASAL_U_HR,
            "timestamp": ts,
        }
        # `enacted` mirrors `suggested` plus `received: true`. Same
        # spelling oref0's `bin/ns-status.js` uses (correctly spelled,
        # lowercase) -- the descendants inherit this.
        enacted = {**determination, "received": True}

        # oref0's pump subtree is LEAN: no bolusIncrement (Trio-specific),
        # no AAPS configuration block, no Loop pumpManagerStatus. Just
        # the four fields the original `bin/ns-status.js` writes.
        pump_subtree = {
            "clock": ts,
            "battery": {"percent": int(state.pump_battery_pct)},
            "reservoir": round(state.reservoir_u, 1),
            "status": {"status": "normal", "suspended": state.pump_suspended},
        }

        # oref0 emits `uploaderBattery` as a TOP-LEVEL int (AAPS-style),
        # NOT a nested `uploader: {...}` object (Loop / Trio-style).
        # Per `bin/ns-status.js#L52-L61`: when uploader_input is a
        # plain number, it's stored as the top-level field. Real
        # oref0 boxes default to this since they read the Pi's battery
        # as a single integer percentage.
        payload = [
            {
                "device": self.device_label,
                "created_at": ts,
                "uploaderBattery": int(state.phone_battery_pct),
                "openaps": {
                    "iob": iob_subtree,
                    "suggested": determination,
                    "enacted": enacted,
                    "version": OREF0_VERSION,
                },
                "pump": pump_subtree,
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/devicestatus.json",
            self._auth_headers,
            payload,
        )

    # ---- treatments -----------------------------------------------------

    def post_meal_bolus(
        self,
        state: PatientState,
        carbs_g: float,
        bolus_u: float,
        posted_at: datetime.datetime,
    ) -> None:
        """oref0 uploads meals as TWO separate treatments at the same
        `created_at`: one `Carb Correction` (carbs only) and one
        `Meal Bolus` (insulin only). The pump-history bridge plus
        Care Portal carb-entry flow naturally splits them; oref0
        doesn't have a `Meal Bolus` shape with bundled carbs.

        Crucially, oref0 PRESERVES the eventType distinction Trio
        dropped: a non-SMB user-administered bolus that covered a
        meal is `"Meal Bolus"` (not generic `"Bolus"`). The
        translator's `_pump_events_mapper` handles `Meal Bolus` →
        bolus pump_event with the correct semantic kind.
        """
        created_at = iso_z(posted_at)
        carb_payload = [
            {
                "eventType": "Carb Correction",
                "created_at": created_at,
                "enteredBy": OREF0_ENTERED_BY,
                "carbs": round(carbs_g, 1),
            }
        ]
        bolus_payload = [
            {
                "eventType": "Meal Bolus",
                "created_at": created_at,
                "enteredBy": OREF0_ENTERED_BY,
                "insulin": bolus_u,
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            carb_payload,
        )
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            bolus_payload,
        )

    def post_correction_bolus(
        self,
        state: PatientState,
        units: float,
        posted_at: datetime.datetime,
    ) -> None:
        """oref0 split: ~80% of corrections fire automatically as
        `eventType: "SMB"` (the SMB algorithm is the modern oref0
        default), ~20% as user-initiated `eventType: "Correction
        Bolus"` (manual via Care Portal or pump key).

        Unlike Trio, oref0 KEEPS the `Correction Bolus` eventType for
        manual corrections -- it doesn't collapse into a generic
        `Bolus`. The translator handles both."""
        # Test the 20% (manual) branch first; equivalent to `is_smb =
        # rng < 0.80` with the branches flipped. Either form gives the
        # same distribution; we test the rarer branch first because
        # `Correction Bolus` payload is more involved than `SMB`.
        is_manual = self._rng.random() < 0.20
        if is_manual:
            payload = [
                {
                    "eventType": "Correction Bolus",
                    "created_at": iso_z(posted_at),
                    "enteredBy": OREF0_ENTERED_BY,
                    "insulin": units,
                }
            ]
        else:
            payload = [
                {
                    "eventType": "SMB",
                    "created_at": iso_z(posted_at),
                    "enteredBy": OREF0_ENTERED_BY,
                    "insulin": units,
                }
            ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )

    def post_temp_basal(
        self,
        state: PatientState,
        rate_u_hr: float,
        duration_min: int,
        posted_at: datetime.datetime,
    ) -> None:
        """oref0 uploads Temp Basals when the pump driver enacts them
        (which, for an SMB-enabled box, is every cycle). Real oref0
        deployments see every loop decision in their NS treatments
        tab. No `automatic` flag, no pump triple, no client `id`."""
        payload = [
            {
                "eventType": "Temp Basal",
                "created_at": iso_z(posted_at),
                "enteredBy": OREF0_ENTERED_BY,
                "rate": rate_u_hr,
                "absolute": rate_u_hr,
                "duration": duration_min,
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )

    def post_site_change(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """oref0 records pump pod/cannula changes as `Site Change`
        treatments. Sourced from pump history `prime` events parsed
        by `lib/pump.js`."""
        payload = [
            {
                "eventType": "Site Change",
                "created_at": iso_z(posted_at),
                "enteredBy": OREF0_ENTERED_BY,
                "notes": "Cannula change (emulated)",
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )

    # ---- private: temp target ------------------------------------------

    def _post_temp_target(
        self,
        posted_at: datetime.datetime,
        *,
        target_mgdl: int,
        duration_min: int,
        reason: str = "Exercise",
    ) -> None:
        """Real oref0 users set Temporary Targets via Nightscout's
        Care Portal during exercise / sleep / sick days. oref0's
        main loop reads them on every cycle to bias `target_bg` in
        determine-basal."""
        payload = [
            {
                "eventType": "Temporary Target",
                "created_at": iso_z(posted_at),
                "enteredBy": OREF0_ENTERED_BY,
                "targetTop": target_mgdl,
                "targetBottom": target_mgdl - 10,
                "duration": duration_min,
                "reason": reason,
                "units": "mg/dl",
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )


# ---------------------------------------------------------------------------
# xDrip4iOS lens (pure CGM uploader, iOS, no closed-loop)
# ---------------------------------------------------------------------------
#
# xDrip4iOS (`JohanDegraeve/xdripswift`) is a pure-CGM Nightscout
# uploader for Apple devices. It reads Dexcom G6/G7 directly via
# Bluetooth, or Libre 2/3 via a transmitter bridge (MiaoMiao, Bubble,
# Atom, etc.) and uploads readings to Nightscout. It is NOT a closed-
# loop system: no algorithm, no automated dosing, no `openaps` /
# `loop.enacted` payload.
#
# Architecturally distinct from every lens shipped so far:
#
# - **No closed-loop output**: NO `openaps` subtree, NO algorithm
#   determination, NO predBGs, NO `loop.enacted`. The lens emits
#   `entries` and (optionally, by user action) `treatments`. The
#   `devicestatus` payload is minimal -- just transmitter battery.
#
# - **`enteredBy: "xDrip4iOS"`** literal on every treatment, per
#   upstream `Source/Managers/Nightscout/NightscoutSyncManager.swift`
#   which hardcodes `ConstantsHomeView.applicationName`.
#
# - **`device` = transmitter name**, not the app: Dexcom direct →
#   `"Dexcom G6"` / `"Dexcom G7"`, Libre via MiaoMiao →
#   `"MiaoMiao"`, etc. Per upstream
#   `Source/Managers/Nightscout/BgReading+Nightscout.swift` which
#   reads `BgReading.deviceName` (the transmitter's identifier).
#
# - **Raw sensor metadata in entries**: every entry POST carries
#   `filtered` and `unfiltered` (raw value × 1000 OR
#   `calculatedValue * 1000` if no raw signal) plus a hardcoded
#   `noise: 1`. Closed-loop lenses don't emit any of these -- they
#   work from glucose values, not raw sensor signal.
#
# - **Transmitter battery in `devicestatus.uploader`**: the field
#   carries the SENSOR/transmitter battery, not the phone's. Dexcom
#   transmitters report a voltage; Libre readers report a percent.
#   Closed-loop lenses' `devicestatus.uploader` carries the phone /
#   rig battery.
#
# - **Treatments**: xDrip4iOS lets users manually enter Bolus,
#   Carbs, Exercise, BG Check, Temp Basal, Site Change, Sensor
#   Start, Pump Battery Change. These all go via the standard NS
#   `treatments.json` POST. xDrip4iOS does NOT generate algorithm-
#   driven treatments (no SMBs, no auto-corrections).
#
# - **No profile upload**: xDrip4iOS reads the user's NS profile to
#   display targets / ISF / CR for follower-mode views, but does
#   not post one. So `ensure_profile()` is a no-op.
#
# - **`noise: 1`**: hardcoded in upstream. Production CGM uploaders
#   sometimes vary noise (CleanSensor / LightNoise / MediumNoise /
#   HeavyNoise / Rejected) but xDrip4iOS always emits 1 (Clean).
#
# - **Translator devicestatus-classification limitation (known)**:
#   the GlycemicGPT translator's `detect_uploader` matches the
#   xDrip family via substring `"xdrip"` in `enteredBy` or `device`.
#   xDrip4iOS treatments stamp `enteredBy: "xDrip4iOS"` (lowercased
#   matches), so treatments classify as `xdrip4ios` correctly. But
#   xDrip4iOS devicestatus records carry `device:
#   "<transmitter-name>"` (e.g., `"Dexcom G6"`) instead of an
#   app-name -- which the heuristic can't match. Real xDrip4iOS
#   deployments hit this same misclassification (devicestatus →
#   `unknown`). No functional impact since no code paths branch on
#   `uploader == "xdrip4ios"`. Documented for the future translator
#   improvement: classify by `uploader.name == "transmitter"` as a
#   secondary signal.
#
# Source-of-truth files cross-checked:
#   - `mapping/xdrip4ios/data-models.md` (entry + treatment shapes)
#   - `mapping/xdrip4ios/nightscout-sync.md` (auth + endpoints)
#   - `mapping/xdrip4ios/treatment-classification.md` (eventType map)
#   - upstream `JohanDegraeve/xdripswift/Source/Managers/Nightscout/
#     NightscoutSyncManager.swift` (sync orchestration)
#   - upstream `JohanDegraeve/xdripswift/Source/Managers/Nightscout/
#     BgReading+Nightscout.swift` (entry shape)


XDRIP4IOS_APP_NAME = "xDrip4iOS"
# Modeled patient runs Dexcom G6 (most-common direct-Bluetooth CGM
# pairing for xDrip4iOS users). Real `device` field gets the actual
# transmitter name; we use `"Dexcom G6"` as our deterministic
# stand-in. Override via `NS_XDRIP4IOS_TRANSMITTER` if you want to
# stress-test the translator's `detect_uploader` against varied
# transmitter strings (e.g., `"MiaoMiao"`, `"Bubble"`,
# `"Dexcom G7"`).
XDRIP4IOS_TRANSMITTER = os.environ.get(
    "NS_XDRIP4IOS_TRANSMITTER", "Dexcom G6"
)
# Dexcom transmitters report battery as a voltage (~3.0-4.5V); Libre
# readers report as percentage. We model Dexcom voltage by default;
# under a Libre transmitter override the value here is still
# voltage-shaped, which is faithful for Dexcom and benign for the
# translator.
XDRIP4IOS_BATTERY_VOLTAGE_DEFAULT = 4.0


class Xdrip4iOSLens(Lens):
    """xDrip4iOS (iOS pure-CGM uploader) lens. See architecture
    comment block above for the full vs-closed-loop diff."""

    name = "xdrip4ios"

    def __init__(
        self, base_url: str, api_secret: str, device_label: str | None = None
    ) -> None:
        super().__init__(base_url, api_secret, device_label)
        # Once-per-sim-day `BG Check` (fingerstick) -- real xDrip4iOS
        # users calibrate ~daily. This is the only treatment-shape
        # event we emit on a fixed schedule; the rest are tied to
        # physiology hooks. Direction-arrow math uses the shared
        # `direction_for(prev_bg, bg)` helper (prev_bg is passed in
        # by the main loop, not held on this lens).
        self._last_bg_check_date: str | None = None
        # Battery drift: real Dexcom transmitter voltage decays from
        # ~4.0V fresh to ~2.6V end-of-life over the sensor lifespan.
        # We start near full and decay slowly per cycle.
        self._transmitter_battery_voltage: float = (
            XDRIP4IOS_BATTERY_VOLTAGE_DEFAULT
        )

    @classmethod
    def default_device_label(cls) -> str:
        # The `device` field carries the transmitter name (NOT the
        # app name). Per upstream `BgReading+Nightscout.swift`.
        return XDRIP4IOS_TRANSMITTER

    # ---- profile --------------------------------------------------------

    def ensure_profile(self) -> None:
        """xDrip4iOS does NOT upload a profile -- it reads the user's
        existing NS profile to render follower-mode targets / ISF /
        CR. Real xDrip4iOS deployments expect the profile to already
        exist (uploaded by the user's pump-side app, or set via the
        Nightscout admin UI). For the emulator we still post a
        minimal profile if none exists, so the test stack has a
        consistent baseline -- but stamp `enteredBy: "openaps"`
        (the default Care Portal sentinel) rather than `"xDrip4iOS"`
        to match the contract that xDrip4iOS doesn't author profiles.
        """
        try:
            existing = http_get(
                self.base_url, "/api/v1/profile.json", self._auth_headers
            )
            if existing:
                return
        except urllib.error.HTTPError:
            pass

        now_iso = iso_z(datetime.datetime.now(datetime.UTC))
        profile_name = "Default"
        payload = {
            "defaultProfile": profile_name,
            "store": {
                profile_name: {
                    "dia": str(DIA_MINUTES // 60),
                    "carbratio": [{"time": "00:00", "value": ICR_GRAMS_PER_UNIT}],
                    "sens": [{"time": "00:00", "value": ISF_MGDL_PER_UNIT}],
                    "basal": [{"time": "00:00", "value": SCHEDULED_BASAL_U_HR}],
                    "target_low": [{"time": "00:00", "value": TARGET_BG_MGDL - 10}],
                    "target_high": [{"time": "00:00", "value": TARGET_BG_MGDL + 10}],
                    "carbs_hr": "20",
                    "delay": "20",
                    "timezone": "UTC",
                    "units": "mg/dl",
                }
            },
            "startDate": now_iso,
            "mills": int(time.time() * 1000),
            "units": "mg/dl",
            # Sentinel `enteredBy: "openaps"` (the Care Portal default
            # author string) signals this profile was NOT authored by
            # xDrip4iOS itself -- per the contract in this lens's
            # docstring, real xDrip4iOS reads profiles but never
            # writes them. Without this field, downstream consumers
            # can't tell whether a profile came from the user's
            # closed-loop app or was a stand-in fixture.
            "enteredBy": "openaps",
        }
        http_post(
            self.base_url, "/api/v1/profile.json", self._auth_headers, [payload]
        )

    # ---- per-tick hook --------------------------------------------------

    def on_tick_start(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """xDrip4iOS has NO closed-loop algorithm and does NOT enact
        temp basals. The patient runs on plain scheduled basal --
        `current_basal_u_hr` returns `SCHEDULED_BASAL_U_HR` when no
        temp is active, which IS the desired behavior. Notably, this
        lens does NOT call `state.set_temp_basal()` -- doing so would
        keep `temp_basal_remaining_min` pinned at the duration on
        every tick, semantically suggesting "this user is on a temp
        basal" when in reality xDrip4iOS users have no algorithm-
        driven temps at all (their basal comes from the pump's own
        scheduled program).

        Real xDrip4iOS users also calibrate sensors with fingerstick
        BG checks roughly once per day; we fire a `BG Check`
        treatment in the morning window to exercise that path.
        """

        # Once-per-sim-day BG Check (fingerstick calibration).
        date_iso = state.sim_time.date().isoformat()
        hour = state.sim_time.hour
        if 7 <= hour < 8 and self._last_bg_check_date != date_iso:
            self._last_bg_check_date = date_iso
            try:
                self._post_bg_check(state, posted_at)
            except Exception as exc:  # noqa: BLE001 - keep loop running
                print(
                    f"[emu] xdrip4ios bg_check post failed: {exc}", flush=True
                )

        # Slow transmitter battery drift (per-cycle): -0.0001 V per
        # 5-min cycle. Floor at 2.6 V (Dexcom end-of-life voltage).
        # From the 4.0 V default this drops the full 1.4 V over
        # ~14000 cycles ≈ 48 sim-days. A real Dexcom G6 transmitter
        # holds near 4.0 V for most of its ~90-day life and drops
        # fast at end-of-life; this monotonic linear stand-in is a
        # rough emulator approximation, faithful enough that the
        # voltage is plausibly in-range for any sim window.
        self._transmitter_battery_voltage = max(
            2.6, self._transmitter_battery_voltage - 0.0001
        )

    # ---- entries --------------------------------------------------------

    def post_entry(
        self,
        state: PatientState,
        prev_bg: float,
        posted_at: datetime.datetime,
    ) -> None:
        """xDrip4iOS entries carry RAW SENSOR METADATA in addition
        to the standard sgv: `filtered`, `unfiltered`, `noise`.
        Per upstream `BgReading+Nightscout.swift`:
        - `filtered = ageAdjustedRawValue * 1000` (raw signal in
          microvolts-or-equivalent, scaled).
        - `unfiltered = rawData * 1000` (or
          `calculatedValue * 1000` if no raw available).
        - `noise = 1` (hardcoded; Clean Sensor signal-quality flag).

        For our emulator we don't have raw sensor data, so we
        synthesize plausible filtered/unfiltered values from the
        physiology BG. This is faithful to what NS receives;
        downstream consumers reading raw signal would see
        `state.bg * 1000` instead of a true sensor microvolts read.
        """
        bg = state.bg
        sgv = int(round(bg))
        # `direction` is set by xDrip4iOS via Dexcom-style trend
        # arrow naming. Use the shared helper (same rules as Loop).
        direction = direction_for(prev_bg, bg)

        payload = [
            {
                "type": "sgv",
                "sgv": sgv,
                "direction": direction,
                "date": int(posted_at.timestamp() * 1000),
                "dateString": iso_z(posted_at),
                "device": self.device_label,
                # Raw sensor metadata, distinctive to xDrip4iOS /
                # xDrip+ entries vs closed-loop-uploader entries.
                "filtered": int(round(bg * 1000)),
                "unfiltered": int(round(bg * 1000)),
                "noise": 1,
            }
        ]
        http_post(
            self.base_url, "/api/v1/entries.json", self._auth_headers, payload
        )

    # ---- devicestatus ---------------------------------------------------

    def post_devicestatus(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """xDrip4iOS devicestatus is MINIMAL -- just transmitter
        battery. NO `openaps` subtree, NO `loop` subtree, NO `pump`
        subtree. Per upstream `NightscoutSyncManager.swift`:

        ```
        {
          "device": "<transmitter name>",
          "uploader": {
            "name": "transmitter",
            "battery": <int> (or voltage as float for Dexcom),
            "batteryVoltage": <voltage> (Dexcom only)
          },
          "created_at": "<ISO>"
        }
        ```

        Distinctive vs closed-loop devicestatus:
        - `uploader.name = "transmitter"` (closed-loop systems use
          the phone-rig name or omit `name` entirely).
        - For Dexcom we add `batteryVoltage` (a float voltage like
          3.5); for Libre readers it's a battery percentage int.
        """
        ts = iso_z(posted_at)
        # Dexcom transmitters report voltage; Libre readers report
        # percent. We model Dexcom (voltage) by default. The integer
        # `battery` field is computed from voltage via the Dexcom
        # convention (4.0V = 100%, 2.6V = 0%, linear).
        voltage = self._transmitter_battery_voltage
        battery_pct = max(
            0, min(100, int(round((voltage - 2.6) / (4.0 - 2.6) * 100)))
        )
        uploader_subtree = {
            "name": "transmitter",
            "battery": battery_pct,
            "batteryVoltage": round(voltage, 3),
        }

        payload = [
            {
                "device": self.device_label,
                "created_at": ts,
                "uploader": uploader_subtree,
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/devicestatus.json",
            self._auth_headers,
            payload,
        )

    # ---- treatments -----------------------------------------------------

    def post_meal_bolus(
        self,
        state: PatientState,
        carbs_g: float,
        bolus_u: float,
        posted_at: datetime.datetime,
    ) -> None:
        """xDrip4iOS users manually enter meal carbs + the bolus
        they took separately via two distinct UI flows -- carbs go
        in `Carbs` treatments, insulin goes in `Bolus` treatments.
        Per upstream `treatment-classification.md`:
        - `TreatmentType.Carbs` → eventType `"Carbs"`
        - `TreatmentType.Insulin` → eventType `"Bolus"`

        Note the `"Carbs"` (not `"Carb Correction"`) -- xDrip4iOS
        uses the simpler eventType. We post both at the same
        `created_at` to model a wizard-driven meal entry."""
        created_at = iso_z(posted_at)
        # Carbs treatment.
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            [
                {
                    "eventType": "Carbs",
                    "created_at": created_at,
                    "enteredBy": XDRIP4IOS_APP_NAME,
                    "carbs": round(carbs_g, 1),
                }
            ],
        )
        # Bolus treatment.
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            [
                {
                    "eventType": "Bolus",
                    "created_at": created_at,
                    "enteredBy": XDRIP4IOS_APP_NAME,
                    "insulin": bolus_u,
                }
            ],
        )

    def post_correction_bolus(
        self,
        state: PatientState,
        units: float,
        posted_at: datetime.datetime,
    ) -> None:
        """xDrip4iOS does NOT emit SMB events -- it has no closed-
        loop algorithm. Manual corrections come through as plain
        `Bolus` treatments (same eventType as meal-time wizard
        boluses; xDrip4iOS doesn't distinguish on the wire).
        Per `treatment-classification.md`: `TreatmentType.Insulin`
        → eventType `"Bolus"` regardless of motivation."""
        payload = [
            {
                "eventType": "Bolus",
                "created_at": iso_z(posted_at),
                "enteredBy": XDRIP4IOS_APP_NAME,
                "insulin": units,
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )

    def post_temp_basal(
        self,
        state: PatientState,
        rate_u_hr: float,
        duration_min: int,
        posted_at: datetime.datetime,
    ) -> None:
        """xDrip4iOS does NOT post Temp Basal treatments
        algorithmically -- there's no algorithm. A user CAN manually
        record a temp basal via the UI (e.g., to log a temporary
        rate they set on their pump), but real-world deployments
        rarely do this. Skip in our emulator -- a Temp Basal posted
        every 5 sim-min would be wildly out-of-band for an xDrip4iOS
        user."""
        return

    # `post_site_change` deliberately NOT overridden -- xDrip4iOS is
    # a pure-CGM uploader with no pump connection, so a `Site Change`
    # event triggered by the patient state's `maybe_refill_reservoir`
    # path (which models a pump pod refill, not an xDrip4iOS-side
    # event) cannot legitimately originate here. Real xDrip4iOS users
    # CAN manually record a Site Change via the in-app treatment-entry
    # UI, but that's a UI-driven event not derived from pump
    # reservoir state -- we'd need a separate scheduled-entry hook to
    # model it, not a pump-state callback. Inherit `Lens.post_site_change`
    # (no-op base impl).

    # ---- private: BG Check (fingerstick calibration) -------------------

    def _post_bg_check(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """Real xDrip4iOS users record fingerstick BG checks for
        sensor calibration (especially Dexcom G6 / Libre 1). Per
        upstream `treatment-classification.md`:
        `TreatmentType.BgCheck` → eventType `"BG Check"` with
        `glucose`, `glucoseType: "Finger"`, `units: "mg/dl"`.

        Sim a fingerstick that's slightly off the CGM reading (real
        meters disagree with sensors by ~5-15 mg/dL); use the current
        BG +/- a small bias."""
        # Fingerstick "true" BG = CGM reading +/- ~10 mg/dL noise.
        # In an emulator we just pass the CGM value through unchanged
        # -- our patient state has no separate "true plasma BG" field.
        glucose_value = int(round(state.bg))
        payload = [
            {
                "eventType": "BG Check",
                "created_at": iso_z(posted_at),
                "enteredBy": XDRIP4IOS_APP_NAME,
                "glucose": glucose_value,
                "glucoseType": "Finger",
                "units": "mg/dl",
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )


# ---------------------------------------------------------------------------
# xDrip+ lens (Android pure-CGM uploader, predecessor to xdrip4ios)
# ---------------------------------------------------------------------------
#
# xDrip+ (`NightscoutFoundation/xDrip`, Java/Kotlin) is the Android
# pure-CGM Nightscout uploader. It predates xDrip4iOS by ~5 years and
# supports a wider range of CGM data sources (Dexcom G4/G5/G6/G7,
# Libre 1/2/3, LimiTTer, Bluetooth Wixel, MiaoMiao, Bubble, NS
# Follower, etc.). Like xdrip4ios it's NOT a closed-loop system: no
# algorithm, no automated dosing, no `openaps` payload.
#
# This lens is the SIBLING of `xdrip4ios`, but the wire format
# diverges on every important field. Top divergences:
#
# - **`enteredBy: "xdrip"`** (lowercase, no plus, no version), per
#   upstream `app/src/main/java/com/eveningoutpost/dexdrip/models/
#   Treatments.java`'s `XDRIP_TAG = "xdrip"` constant. xdrip4ios
#   stamps `"xDrip4iOS"` (title case + version suffix); this lens
#   stamps the bare lowercase string.
#
# - **`device` is `"xDrip-<collection-method>"`**, NOT the bare
#   transmitter name xdrip4ios uses. The collection method comes
#   from the `DexCollectionType` enum in upstream
#   `app/src/main/java/com/eveningoutpost/dexdrip/utils/
#   DexCollectionType.java` -- common values include `DexcomG6`,
#   `DexcomG5`, `LimiTTer`, `BluetoothWixel`, `MiaoMiao`,
#   `LibreReceiver`, `NSFollower`. So entries from a typical
#   Dexcom G6 setup stamp `device: "xDrip-DexcomG6"`.
#
# - **Entries carry MORE metadata than xdrip4ios**:
#   - `filtered = ageAdjustedFiltered() * 1000` (note: `Filtered`
#     not `RawValue`; the Android calculation uses Kalman-filter-
#     smoothed values where iOS uses unsmoothed raw signal).
#   - `unfiltered = usedRaw() * 1000` (the raw sensor signal
#     "actually used" by the calc pipeline -- distinct from
#     `filtered`, unlike xdrip4ios where both fields read from
#     the same source).
#   - `noise` carries the ACTUAL ordinal noise level
#     (1=CleanSensor, 2=LightNoise, 3=MediumNoise, 4=HeavyNoise,
#     5=Rejected). xdrip4ios hardcodes `1`.
#   - `delta` (xDrip+ only) -- BG-change-rate calculated from
#     slope. Computed `slope * 5 * 60 * 1000` per upstream
#     `populateV1APIBGEntry()`.
#   - `rssi` (xDrip+ only) -- hardcoded `100` per upstream.
#
# - **Devicestatus `device` is `"xDrip-<Build.MANUFACTURER><Build.MODEL>"`**
#   (e.g., `"xDrip-Pixel7Pro"`), per upstream `postDeviceStatus()`.
#   xdrip4ios uses the transmitter name on devicestatus too. xDrip+
#   may post MULTIPLE devicestatus records per cycle (phone, bridge,
#   transmitter) when the user enables the corresponding "send
#   battery" preferences -- by default just the phone's record.
#
# - **Treatment vocabulary is RICHER than xdrip4ios**:
#   - Carbs: `"Carb Correction"` (NOT xdrip4ios's bare `"Carbs"`)
#   - Boluses: distinguishes `"Snack Bolus"`, `"Meal Bolus"`,
#     `"Correction Bolus"` (NOT xdrip4ios's flat `"Bolus"`)
#   - Sensor: `"Sensor Start"` AND `"Sensor Stop"` (xdrip4ios only
#     emits Start)
#   - `insulinJSON` array for multi-insulin tracking (NovoRapid +
#     Tresiba, etc.) -- xdrip4ios doesn't model multi-insulin.
#
# - **No profile upload**, same as xdrip4ios. xDrip+ is a follower-
#   mode consumer of the user's NS profile, never an author.
#
# Translator-side note: the `detect_uploader` heuristic
# (`apps/api/src/services/integrations/nightscout/models.py`)
# matches `"xdrip" in eb` so xDrip+ treatments classify as
# `xdrip+` correctly via `enteredBy: "xdrip"`. The `device` form
# `"xDrip-DexcomG6"` does start with `"xdrip-"` (lowercased), so
# the prefix path also classifies. Devicestatus posts with `device:
# "xDrip-Pixel7Pro"` likewise classifies via the prefix.
#
# Source-of-truth files cross-checked:
#   - `mapping/xdrip-android/` (data-models + nightscout-sync)
#   - upstream `NightscoutFoundation/xDrip/app/src/main/java/com/
#     eveningoutpost/dexdrip/utilitymodels/NightscoutUploader.java`
#     (REST upload logic, payload builders)
#   - upstream `app/src/main/java/com/eveningoutpost/dexdrip/
#     models/Treatments.java` (XDRIP_TAG = "xdrip")
#   - upstream `app/src/main/java/com/eveningoutpost/dexdrip/
#     models/BgReading.java` (noise / filtered / raw helpers)
#   - upstream `app/src/main/java/com/eveningoutpost/dexdrip/
#     utils/DexCollectionType.java` (collection-method enum)


XDRIP_PLUS_APP_NAME = "xdrip"  # lowercase, per upstream Treatments.java
# Modeled patient runs Dexcom G6 (most-common direct-Bluetooth CGM
# pairing for xDrip+ users). The full `device` string composes as
# `"xDrip-<collection-method>"`. Override via
# `NS_XDRIP_PLUS_COLLECTION` for `LimiTTer` / `BluetoothWixel` /
# `MiaoMiao` / `LibreReceiver` / `NSFollower` / etc.
XDRIP_PLUS_COLLECTION = os.environ.get(
    "NS_XDRIP_PLUS_COLLECTION", "DexcomG6"
)
XDRIP_PLUS_DEVICE_LABEL = f"xDrip-{XDRIP_PLUS_COLLECTION}"
# Devicestatus `device` carries the phone's manufacturer+model, per
# upstream `postDeviceStatus()`. Override via
# `NS_XDRIP_PLUS_PHONE_MODEL` to match a specific Android device
# (e.g., `"GooglePixel8"` / `"SamsungS23"` / `"OnePlus11"`).
XDRIP_PLUS_PHONE_MODEL = os.environ.get(
    "NS_XDRIP_PLUS_PHONE_MODEL", "Pixel7Pro"
)
XDRIP_PLUS_DEVICESTATUS_DEVICE = f"xDrip-{XDRIP_PLUS_PHONE_MODEL}"


class XdripPlusLens(Lens):
    """xDrip+ (Android pure-CGM uploader) lens. See architecture
    comment block above for the full vs-xdrip4ios divergence list."""

    name = "xdrip_plus"

    def __init__(
        self, base_url: str, api_secret: str, device_label: str | None = None
    ) -> None:
        super().__init__(base_url, api_secret, device_label)
        # Once-per-sim-day `BG Check` (fingerstick) -- real xDrip+
        # users calibrate ~daily. xdrip4ios pattern.
        self._last_bg_check_date: str | None = None
        # The most-recent BG VALUE this lens itself has POSTED. Used
        # solely to determine whether `delta` should be emitted on
        # the next entry: real xDrip+ omits `delta` on the very
        # first reading (slope unknown -- no prior reading in its
        # own DB to compute the change against). The main loop's
        # `prev_bg` is unreliable here because it's the patient
        # state's pre-tick BG, which is always set (defaulting to
        # the starting BG on the first call) -- it doesn't capture
        # "have I, the lens, posted anything yet?". Tracking the
        # lens's own posted history is the correct signal.
        self._last_posted_bg: float | None = None

    @classmethod
    def default_device_label(cls) -> str:
        # Entries `device` field carries the transmitter wrapped in
        # the `"xDrip-"` prefix. Per upstream
        # `getDeviceString()` in NightscoutUploader.java.
        return XDRIP_PLUS_DEVICE_LABEL

    # ---- profile --------------------------------------------------------

    def ensure_profile(self) -> None:
        """xDrip+ does NOT upload a profile -- it reads the user's
        existing NS profile to render follower-mode targets / ISF /
        CR. Same contract as xdrip4ios. We post a baseline profile
        if NS has none (so the test stack has a consistent state)
        and stamp `enteredBy: "openaps"` (the Care Portal sentinel)
        to honor the contract that xDrip+ doesn't author profiles.
        """
        try:
            existing = http_get(
                self.base_url, "/api/v1/profile.json", self._auth_headers
            )
            if existing:
                return
        except urllib.error.HTTPError:
            pass

        now_iso = iso_z(datetime.datetime.now(datetime.UTC))
        profile_name = "Default"
        payload = {
            "defaultProfile": profile_name,
            "store": {
                profile_name: {
                    "dia": str(DIA_MINUTES // 60),
                    "carbratio": [{"time": "00:00", "value": ICR_GRAMS_PER_UNIT}],
                    "sens": [{"time": "00:00", "value": ISF_MGDL_PER_UNIT}],
                    "basal": [{"time": "00:00", "value": SCHEDULED_BASAL_U_HR}],
                    "target_low": [{"time": "00:00", "value": TARGET_BG_MGDL - 10}],
                    "target_high": [{"time": "00:00", "value": TARGET_BG_MGDL + 10}],
                    "carbs_hr": "20",
                    "delay": "20",
                    "timezone": "UTC",
                    "units": "mg/dl",
                }
            },
            "startDate": now_iso,
            "mills": int(time.time() * 1000),
            "units": "mg/dl",
            # Sentinel: xDrip+ doesn't author profiles -- per
            # upstream, it's a follower-mode consumer only. Stamp
            # `"openaps"` (the Care Portal default) so downstream
            # consumers can correctly tell this profile wasn't
            # authored by xDrip+.
            "enteredBy": "openaps",
        }
        http_post(
            self.base_url, "/api/v1/profile.json", self._auth_headers, [payload]
        )

    # ---- per-tick hook --------------------------------------------------

    def on_tick_start(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """xDrip+ has NO closed-loop algorithm and does NOT enact
        temp basals. The patient runs on plain scheduled basal --
        same pattern as xdrip4ios.

        Real xDrip+ users calibrate Dexcom G4/G5/G6/G7 sensors with
        fingerstick BG checks roughly once per day; we fire one in
        the morning window to exercise the path."""
        date_iso = state.sim_time.date().isoformat()
        hour = state.sim_time.hour
        if 7 <= hour < 8 and self._last_bg_check_date != date_iso:
            self._last_bg_check_date = date_iso
            try:
                self._post_bg_check(state, posted_at)
            except Exception as exc:  # noqa: BLE001 - keep loop running
                print(
                    f"[emu] xdrip_plus bg_check post failed: {exc}", flush=True
                )

    # ---- entries --------------------------------------------------------

    def post_entry(
        self,
        state: PatientState,
        prev_bg: float,
        posted_at: datetime.datetime,
    ) -> None:
        """xDrip+ entries carry MORE metadata than xdrip4ios:
        `filtered`, `unfiltered`, `noise` (actual ordinal),
        `delta` (BG-change rate), `rssi`. Per upstream
        `populateV1APIBGEntry()` in NightscoutUploader.java.

        For our emulator we approximate:
        - `filtered = bg * 1000` (Kalman-smoothed value; real xDrip+
          differs from `unfiltered` after noise pipeline runs, but
          for the emulator's clean trace they collapse).
        - `unfiltered = bg * 1000 + 50` (raw sensor signal; offset
          by 50 microvolts to keep the two fields distinguishable
          on the wire even though our patient state has no separate
          smoothed/unsmoothed tracks. Matches the upstream contract
          that the two fields can differ).
        - `noise = 1` (CleanSensor; the ordinal range 1-5 is
          documented but our patient state has no noise model).
        - `delta = bg - prev_bg` (mg/dL change over the 5-min cycle).
          Upstream `slope_mgdl_per_ms * 5 * 60 * 1000` reduces to
          mg/dL change over a 5-minute window -- same units as
          (bg - prev_bg) for a smooth trace. Omitted entirely on
          the very first reading (no prior BG to compare against),
          matching upstream's behavior when slope is unknown.
        - `rssi = 100` (hardcoded per upstream).
        """
        bg = state.bg
        sgv = int(round(bg))
        direction = direction_for(prev_bg, bg)
        # Delta only included when this lens has previously posted
        # an entry -- upstream xDrip+ omits the field on the very
        # first reading (slope unknown). The main loop's `prev_bg`
        # is unreliable here because it always carries the patient
        # state's pre-tick BG (defaulting to the starting BG on the
        # first call). Use this lens's own `_last_posted_bg` --
        # `None` until the first post, set after every post.
        delta_mgdl: float | None = (
            None
            if self._last_posted_bg is None
            else round(bg - self._last_posted_bg, 1)
        )

        entry: dict[str, object] = {
            "type": "sgv",
            "sgv": sgv,
            "direction": direction,
            "date": int(posted_at.timestamp() * 1000),
            "dateString": iso_z(posted_at),
            "device": self.device_label,
            # Raw sensor metadata (xDrip family). `filtered` is the
            # Kalman-smoothed value, `unfiltered` is the raw signal.
            # On real xDrip+ the two diverge after noise pipeline
            # runs; we offset `unfiltered` by 50 microvolts to keep
            # the two fields distinguishable on the wire.
            "filtered": int(round(bg * 1000)),
            "unfiltered": int(round(bg * 1000)) + 50,
            "noise": 1,  # CleanSensor; ordinal 1-5 in upstream
            "rssi": 100,
            "sysTime": iso_z(posted_at),
        }
        if delta_mgdl is not None:
            entry["delta"] = delta_mgdl
        http_post(
            self.base_url,
            "/api/v1/entries.json",
            self._auth_headers,
            [entry],
        )
        # Record the BG we just posted so the next call can compute
        # delta against it.
        self._last_posted_bg = bg

    # ---- devicestatus ---------------------------------------------------

    def post_devicestatus(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """xDrip+ devicestatus is minimal (just uploader.battery
        like xdrip4ios) BUT the `device` field carries the phone
        model (e.g., `"xDrip-Pixel7Pro"`), NOT the transmitter
        name. Per upstream `postDeviceStatus()`.

        xDrip+ can post MULTIPLE devicestatus records per cycle
        (phone, Bluetooth bridge, transmitter) when the user
        enables `send_bridge_battery_to_nightscout` etc. -- by
        default just the phone. We model the default (phone-only)."""
        ts = iso_z(posted_at)
        # Phone battery (the "uploader" in xDrip+ terms is the
        # Android phone running the app).
        uploader_subtree = {
            "name": "transmitter",  # NS-historical; xDrip+ keeps the
                                    # field for compatibility even
                                    # though this record is the phone
            "battery": int(state.phone_battery_pct),
        }

        payload = [
            {
                "device": XDRIP_PLUS_DEVICESTATUS_DEVICE,
                "created_at": ts,
                "uploader": uploader_subtree,
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/devicestatus.json",
            self._auth_headers,
            payload,
        )

    # ---- treatments -----------------------------------------------------

    def post_meal_bolus(
        self,
        state: PatientState,
        carbs_g: float,
        bolus_u: float,
        posted_at: datetime.datetime,
    ) -> None:
        """xDrip+ meals use `"Meal Bolus"` for the insulin and
        `"Carb Correction"` for the carbs (NOT xdrip4ios's bare
        `"Carbs"`). Per upstream `populateV1APITreatmentEntry()`
        treatment-event-type mapping in NightscoutUploader.java.

        Each treatment carries a client-generated UUID per upstream
        (`uuid` field, set from local Treatments.uuid). NS server
        doesn't dedupe on this -- it's xDrip+'s own bidirectional
        sync key.
        """
        created_at = iso_z(posted_at)
        # Carb Correction (richer than xdrip4ios's "Carbs").
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            [
                {
                    "eventType": "Carb Correction",
                    "created_at": created_at,
                    "enteredBy": XDRIP_PLUS_APP_NAME,
                    "carbs": round(carbs_g, 1),
                    "uuid": str(uuid.uuid4()),
                }
            ],
        )
        # Meal Bolus (specific event type for wizard-calculated
        # meal doses, vs the generic "Bolus" xdrip4ios uses).
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            [
                {
                    "eventType": "Meal Bolus",
                    "created_at": created_at,
                    "enteredBy": XDRIP_PLUS_APP_NAME,
                    "insulin": bolus_u,
                    "uuid": str(uuid.uuid4()),
                }
            ],
        )

    def post_correction_bolus(
        self,
        state: PatientState,
        units: float,
        posted_at: datetime.datetime,
    ) -> None:
        """xDrip+ corrections use `"Correction Bolus"` (NOT
        xdrip4ios's flat `"Bolus"`). xDrip+ has no algorithm so no
        SMB events; all corrections are user-initiated through the
        treatment-entry UI."""
        payload = [
            {
                "eventType": "Correction Bolus",
                "created_at": iso_z(posted_at),
                "enteredBy": XDRIP_PLUS_APP_NAME,
                "insulin": units,
                "uuid": str(uuid.uuid4()),
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )

    def post_temp_basal(
        self,
        state: PatientState,
        rate_u_hr: float,
        duration_min: int,
        posted_at: datetime.datetime,
    ) -> None:
        """xDrip+ does not generate Temp Basal treatments
        algorithmically (no algorithm). Skip in our emulator -- a
        Temp Basal posted every 5 sim-min would be wildly out-of-
        band for an xDrip+ user, just like for xdrip4ios."""
        return

    # `post_site_change` deliberately NOT overridden -- xDrip+ is a
    # pure-CGM uploader with no pump connection, so a `Site Change`
    # event triggered by the patient state's `maybe_refill_reservoir`
    # path (which models a pump pod refill, not an xDrip+-side
    # event) cannot legitimately originate here. Real xDrip+ users
    # CAN manually record a Site Change via the treatment-entry UI,
    # but that's a UI-driven event not derived from pump reservoir
    # state -- we'd need a separate scheduled-entry hook to model
    # it. Inherit `Lens.post_site_change` (no-op base impl).

    # ---- private: BG Check ---------------------------------------------

    def _post_bg_check(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        """Real xDrip+ users record fingerstick BG checks for
        sensor calibration. Per upstream `populateV1APITreatmentEntry()`:
        `eventType: "BG Check"` with `glucose` + `glucoseType:
        "Finger"` + `units: "mg/dl"`. Same shape as xdrip4ios."""
        glucose_value = int(round(state.bg))
        payload = [
            {
                "eventType": "BG Check",
                "created_at": iso_z(posted_at),
                "enteredBy": XDRIP_PLUS_APP_NAME,
                "glucose": glucose_value,
                "glucoseType": "Finger",
                "units": "mg/dl",
                "uuid": str(uuid.uuid4()),
            }
        ]
        http_post(
            self.base_url,
            "/api/v1/treatments.json",
            self._auth_headers,
            payload,
        )


# ---------------------------------------------------------------------------
# Lens registry
# ---------------------------------------------------------------------------

LENSES: dict[str, type[Lens]] = {
    "loop": LoopLens,
    "aaps_v1": AapsV1Lens,
    "aaps_v3": AapsV3Lens,
    "trio": TrioLens,
    "oref0": Oref0Lens,
    "xdrip4ios": Xdrip4iOSLens,
    "xdrip_plus": XdripPlusLens,
    # Future: "iaps": IapsLens, "librelink_up": LibreLinkUpLens,
    # "share2ns": Share2NsLens, "tconnectsync": TConnectSyncLens,
    # "manual": ManualLens.
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


class _AuthError(Exception):
    """Sentinel exception: NS rejected an in-loop request with 401/403.

    Distinct from the profile-setup auth check at startup, which
    handles 401/403 inline. Inside the main loop we want the same
    fail-loud behavior so a stale secret doesn't quietly turn into
    an infinite stream of 401s.
    """

    def __init__(self, label: str, code: int) -> None:
        super().__init__(f"{label}: HTTP {code}")
        self.label = label
        self.code = code


def _post_or_log(label: str, fn, *args) -> None:
    """Call `fn(*args)` and translate failures.

    Auth failures (401 / 403) raise `_AuthError` so the main loop
    can exit. Transient upstream failures (other HTTP codes,
    URLError, unexpected exceptions) are logged and swallowed so
    one bad tick doesn't kill the whole run.
    """
    try:
        fn(*args)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise _AuthError(label, exc.code) from exc
        print(f"[emu] {label} post failed: {exc}", flush=True)
    except urllib.error.URLError as exc:
        print(f"[emu] {label} post failed: {exc}", flush=True)
    except Exception as exc:  # noqa: BLE001 - keep loop running
        print(f"[emu] unexpected error on {label}: {exc}", flush=True)


def _parse_float(name: str, default: str) -> float | None:
    raw = os.environ.get(name, default)
    try:
        value = float(raw)
    except ValueError:
        print(f"ERROR: {name} must be a number (got {raw!r})", file=sys.stderr)
        return None
    if not math.isfinite(value):
        print(
            f"ERROR: {name} must be a finite number (got {raw!r})",
            file=sys.stderr,
        )
        return None
    return value


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Multi-lens Nightscout emulator for GlycemicGPT contributors.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available lenses: {', '.join(LENSES.keys())}",
    )
    parser.add_argument(
        "--platform",
        default=os.environ.get("NS_PLATFORM", "loop"),
        choices=sorted(LENSES.keys()),
        help='Which platform to emulate. Default: "loop".',
    )
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    lens_cls = LENSES.get(args.platform)
    if lens_cls is None:
        print(
            f"ERROR: unknown platform {args.platform!r}; "
            f"available: {sorted(LENSES.keys())}",
            file=sys.stderr,
        )
        return 2

    base_url = os.environ.get("NS_BASE_URL", "http://127.0.0.1:1337")
    secret = os.environ.get("NS_API_SECRET")
    if not secret:
        print(
            "ERROR: NS_API_SECRET environment variable is required.\n"
            "Set it to the plaintext API_SECRET of your target "
            "Nightscout instance.",
            file=sys.stderr,
        )
        return 2

    compression = _parse_float("NS_TIME_COMPRESSION", "1")
    if compression is None:
        return 2
    if compression <= 0:
        print("ERROR: NS_TIME_COMPRESSION must be > 0", file=sys.stderr)
        return 2
    duration_hours = _parse_float("NS_DURATION_HOURS", "0")
    if duration_hours is None:
        return 2
    if duration_hours < 0:
        print(
            "ERROR: NS_DURATION_HOURS must be >= 0 (0 = unbounded)",
            file=sys.stderr,
        )
        return 2
    starting_bg = _parse_float("NS_STARTING_BG", "120")
    if starting_bg is None:
        return 2
    if starting_bg <= 0:
        print("ERROR: NS_STARTING_BG must be > 0", file=sys.stderr)
        return 2
    seed_env = os.environ.get("NS_RANDOM_SEED")
    if seed_env is not None:
        try:
            random.seed(int(seed_env))
        except ValueError:
            print(
                f"ERROR: NS_RANDOM_SEED must be an int (got {seed_env!r})",
                file=sys.stderr,
            )
            return 2

    # 1 simulated day = 288 ticks. Wall seconds per tick:
    #   compression=1   -> 300s wall/tick (realtime, 24 wall-hr/day)
    #   compression=10  -> 30s  wall/tick (~144 wall-min/day)
    #   compression=60  -> 5s   wall/tick (~24 wall-min/day)
    wall_seconds_per_tick = 300.0 / compression

    lens = lens_cls(base_url=base_url, api_secret=secret)
    print(
        f"[emu] platform={lens.name} target={base_url} "
        f"compression={compression}x (wall {wall_seconds_per_tick:.1f}s/tick) "
        f"duration={duration_hours}h sim {'(unbounded)' if duration_hours == 0 else ''}",
        flush=True,
    )

    try:
        lens.ensure_profile()
        print(f"[emu] profile ensured for {lens.name}", flush=True)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            print(
                f"[emu] FATAL: HTTP {exc.code} {exc.reason} on profile -- "
                "check NS_API_SECRET. Aborting.",
                file=sys.stderr,
            )
            return 1
        print(
            f"[emu] WARN: profile ensure HTTP {exc.code} {exc.reason} -- "
            "continuing without profile.",
            flush=True,
        )
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.gaierror):
            print(
                f"[emu] FATAL: cannot resolve {base_url!r} ({exc.reason}). Aborting.",
                file=sys.stderr,
            )
            return 1
        print(
            f"[emu] WARN: profile ensure {exc.reason} -- continuing.",
            flush=True,
        )

    state = PatientState(
        starting_bg=starting_bg,
        starting_sim_time=datetime.datetime.now(datetime.UTC),
    )

    stopping = False

    def _on_signal(signum, _frame):  # type: ignore[no-untyped-def]
        nonlocal stopping
        print(f"\n[emu] caught signal {signum}, stopping", flush=True)
        stopping = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    sim_minutes_max = duration_hours * 60.0 if duration_hours > 0 else math.inf
    last_log_at = time.monotonic()

    while not stopping and state.sim_minute < sim_minutes_max:
        prev_bg = state.bg
        # All NS-facing timestamps for this tick share one wall-clock
        # instant. This is the entire reason sim_time and posted_at
        # are separated -- under any compression > 1, sim_time runs
        # faster than wall clock and would future-date NS records.
        posted_at = datetime.datetime.now(datetime.UTC)

        # Lens hook: closed-loop algorithms decide a new temp basal
        # here so it affects this tick's physiology.
        try:
            lens.on_tick_start(state, posted_at)
        except Exception as exc:  # noqa: BLE001 - keep loop running
            print(f"[emu] lens.on_tick_start failed: {exc}", flush=True)

        # Decide on meals / corrections BEFORE advancing -- so the
        # newly-added boluses / carbs affect THIS tick's BG move.
        meal = state.maybe_meal()
        correction = None
        if meal is not None:
            carbs_g, bolus_u = meal
            state.consume_carbs(carbs_g)
            state.deliver_bolus(bolus_u, at=posted_at)
        else:
            correction = state.maybe_correction()
            if correction is not None:
                state.deliver_bolus(correction, at=posted_at)
                state.last_correction_min = state.sim_minute

        # Reservoir below threshold? Refill (and the lens may post
        # a Site Change treatment).
        refilled = state.maybe_refill_reservoir()

        state.advance_5_min()

        # Posters -- order: entry, then devicestatus, then any
        # treatments triggered this tick. Each call wrapped so a
        # transient upstream failure doesn't drop the whole tick.
        # Auth failures (401 / 403) raise out so we can fail loud
        # rather than spin forever spamming 401s.
        try:
            _post_or_log("entry", lens.post_entry, state, prev_bg, posted_at)
            _post_or_log("devicestatus", lens.post_devicestatus, state, posted_at)
            # Loop posts a Temp Basal every cycle, regardless of rate
            # change. Future lenses (AAPS / Trio / oref0) may post on
            # rate change only -- when those land, this every-tick
            # post should move into a per-lens `on_tick_end` hook on
            # the Lens contract.
            _post_or_log(
                "temp basal",
                lens.post_temp_basal,
                state,
                state.temp_basal_rate_u_hr,
                LOOP_TEMP_BASAL_DURATION_MIN,
                posted_at,
            )
            if meal is not None:
                _post_or_log(
                    "meal bolus",
                    lens.post_meal_bolus,
                    state,
                    meal[0],
                    meal[1],
                    posted_at,
                )
            elif correction is not None:
                _post_or_log(
                    "correction",
                    lens.post_correction_bolus,
                    state,
                    correction,
                    posted_at,
                )
            if refilled:
                _post_or_log(
                    "site-change",
                    lens.post_site_change,
                    state,
                    posted_at,
                )
        except _AuthError as auth_exc:
            print(
                f"[emu] FATAL: HTTP {auth_exc.code} on {auth_exc.label} -- "
                "check NS_API_SECRET. Aborting.",
                file=sys.stderr,
            )
            return 1

        # Periodic status, not every tick.
        now = time.monotonic()
        if now - last_log_at >= 30.0:
            last_log_at = now
            print(
                f"[emu] sim={state.sim_time.isoformat(timespec='seconds')} "
                f"bg={state.bg:.0f} iob={state.iob:.2f} cob={state.cob:.1f} "
                f"basal={state.current_basal_u_hr:.2f} "
                f"reservoir={state.reservoir_u:.1f}U "
                f"battery={state.pump_battery_pct:.0f}% "
                f"phone={state.phone_battery_pct:.0f}%"
                f"{' charging' if state.phone_is_charging else ''}",
                flush=True,
            )

        # Sleep until the next tick; chunked so SIGINT lands quickly.
        slept = 0.0
        while slept < wall_seconds_per_tick and not stopping:
            chunk = min(0.5, wall_seconds_per_tick - slept)
            time.sleep(chunk)
            slept += chunk

    print(
        f"[emu] done. simulated {state.sim_minute / 60:.1f} hours.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
