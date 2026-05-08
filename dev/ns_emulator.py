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
  - loop : Loop (Apple iPhone closed-loop, NS API v1, SHA-1 secret)

Planned (each its own PR -- see dev/README.md for status):
  - aaps_v1, aaps_v3, trio, oref0, iaps, xdrip_plus, xdrip4ios,
    librelink_up, share2ns, tconnectsync, manual

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

        now_iso = iso_z(datetime.datetime.now(datetime.UTC))
        profile_name = "AAPS"
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
            [payload],
        )

    # ---- per-tick hooks -------------------------------------------------

    def on_tick_start(self, state: PatientState, posted_at: datetime.datetime) -> None:
        """Same loop-decision approximation as Loop: every cycle,
        the algorithm chooses a temp basal rate. AAPS does this
        every 5 sim-min via the SMB algorithm (`OpenAPSSMBPlugin`).
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
        # AAPS-uploaded entries carry an `app` field identifying the
        # uploader; the rest of the shape is the same as any other
        # uploader.
        payload = [
            {
                "type": "sgv",
                "sgv": int(round(state.bg)),
                "direction": direction_for(prev_bg, state.bg),
                "date": int(posted_at.timestamp() * 1000),
                "dateString": iso_z(posted_at),
                "device": self.device_label,
                "app": "AAPS",
            }
        ]
        http_post(self.base_url, "/api/v1/entries.json", self._auth_headers, payload)

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
        payload = [
            {
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
        ]
        http_post(
            self.base_url,
            "/api/v1/devicestatus.json",
            self._auth_headers,
            payload,
        )

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
        payload = [
            {
                "eventType": "Meal Bolus",
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "device": self.device_label,
                "insulin": bolus_u,
                "carbs": round(carbs_g, 1),
                "type": "NORMAL",
                "isSMB": False,
                "insulinType": AAPS_INSULIN_TYPE,
                **self._aaps_pump_dedup_fields(),
            }
        ]
        http_post(self.base_url, "/api/v1/treatments.json", self._auth_headers, payload)

    def post_correction_bolus(
        self,
        state: PatientState,
        units: float,
        posted_at: datetime.datetime,
    ) -> None:
        # AAPS automated corrections come through as `eventType: "SMB"`
        # with `automatic: true` and `type: "SMB"`. Manual corrections
        # are `eventType: "Correction Bolus"` without those flags.
        # We model the patient as using AAPS-SMB (the modern default)
        # so corrections fire as SMBs.
        payload = [
            {
                "eventType": "SMB",
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "device": self.device_label,
                "insulin": units,
                "automatic": True,
                "type": "SMB",
                "isSMB": True,
                "insulinType": AAPS_INSULIN_TYPE,
                **self._aaps_pump_dedup_fields(),
            }
        ]
        http_post(self.base_url, "/api/v1/treatments.json", self._auth_headers, payload)

    def post_temp_basal(
        self,
        state: PatientState,
        rate_u_hr: float,
        duration_min: int,
        posted_at: datetime.datetime,
    ) -> None:
        # AAPS posts `duration` in MINUTES on Temp Basal treatments
        # (Loop posts the same field in seconds). Real AAPS does this
        # every loop cycle in absolute mode. The `type` field carries
        # the AAPS subtype (NORMAL / EMULATED_PUMP_SUSPEND /
        # PUMP_SUSPEND) which our translator preserves into
        # `metadata_json.aaps_type`.
        delivered = round(rate_u_hr * (duration_min / 60.0), 3)
        payload = [
            {
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
        ]
        http_post(self.base_url, "/api/v1/treatments.json", self._auth_headers, payload)

    def post_site_change(
        self, state: PatientState, posted_at: datetime.datetime
    ) -> None:
        # AAPS uses `Site Change` for cannula change; the upstream
        # spec at mapping/aaps/nsclient-schema.md says the eventType
        # enum value is CANNULA_CHANGE -> "Site Change".
        # NOTE: per `nsclient-schema.md`, `identifier` is server-
        # assigned; AAPS clients don't include it on POST. We
        # follow that convention and let NS assign `_id`.
        payload = [
            {
                "eventType": "Site Change",
                "created_at": iso_z(posted_at),
                "enteredBy": self.device_label,
                "device": self.device_label,
                "notes": "Cannula change (emulated)",
            }
        ]
        http_post(self.base_url, "/api/v1/treatments.json", self._auth_headers, payload)


# ---------------------------------------------------------------------------
# Lens registry
# ---------------------------------------------------------------------------

LENSES: dict[str, type[Lens]] = {
    "loop": LoopLens,
    "aaps_v1": AapsV1Lens,
    # Future: "aaps_v3": AapsV3Lens,
    # "trio": TrioLens, "oref0": Oref0Lens, "iaps": IapsLens,
    # "xdrip_plus": XdripPlusLens, "xdrip4ios": Xdrip4iOSLens,
    # "librelink_up": LibreLinkUpLens, "share2ns": Share2NsLens,
    # "tconnectsync": TConnectSyncLens, "manual": ManualLens.
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
