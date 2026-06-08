"""Cross-source pump-event dedupe hashing (Story 43.11).

The same physical bolus / basal change can be reported by two
integrations -- e.g. Tandem cloud sync reports the *delivered* bolus
while a Loop-via-Nightscout connection reports its *recommended* bolus
for the same physical pump. These can disagree by a few hundredths of a
unit or by a few seconds, which defeats the exact-match natural-key
dedupe ``(user_id, event_timestamp, event_type)``. This module computes
a deliberately-coarse content hash so near-matches collapse to a single
row via the partial unique index ``(user_id, dedupe_hash)``.

Granularity (intentionally narrow -- see Story 43.11 "Tunables"):

* timestamp rounded to the nearest 30 seconds
* units rounded to one decimal place (0.1 U)

Accepted trade-offs (documented, not bugs):

* **Same-source collapse.** The index is global per user, not scoped by
  ``source``. Two *genuinely distinct* deliveries from the SAME source
  that land in the same 30 s / 0.1 U bucket (e.g. two manual 2.5 U
  boluses 15 s apart) also collapse to one row. The story accepts this
  false-positive risk for tightly-spaced same-size deliveries in
  exchange for collapsing the common cross-source duplicate; it is rare
  in practice (automated corrections are minutes apart and rarely the
  same rounded size).
* **event_type is part of the key.** A delivery a closed loop labels a
  ``BOLUS`` (Nightscout SMB) but Tandem labels a ``CORRECTION``
  (Control-IQ automation) hashes differently and is NOT collapsed.
  Cross-source dedupe therefore covers manual boluses reliably but only
  partially covers automated corrections. Widening this would require
  cross-mapping event types between uploaders -- out of scope here.

The hash is computed with :class:`~decimal.Decimal` quantization so the
same logical event always produces the same digest regardless of binary
float representation. The Alembic backfill migration inlines this exact
formula, so historical rows hash identically to new writes (guarded by a
parity test in ``tests/test_pump_event_dedupe.py``).
"""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from src.models.pump_data import PumpEventType

_UNIT_QUANTUM = Decimal("0.1")
_TIME_BUCKET_SECONDS = 30

# Only insulin-DELIVERY events participate in cross-source dedupe. Telemetry
# events also populate `units` -- RESERVOIR stores units-remaining, BATTERY a
# percentage -- so hashing them would collapse legitimately-distinct status
# snapshots reported by two uploaders. The double-counting this story targets
# is in TDD / bolus_count, which only deliveries feed.
_DELIVERY_EVENT_TYPE_VALUES = frozenset({"bolus", "correction", "combo_bolus", "basal"})


def compute_pump_event_dedupe_hash(
    *,
    user_id: uuid.UUID | str,
    event_type: PumpEventType | str,
    event_timestamp: datetime,
    units: float | None,
    duration_minutes: int | None,
) -> str | None:
    """Return the cross-source dedupe hash for a pump event, or ``None``.

    ``None`` is returned for events that carry no insulin amount
    (``units is None``) -- notes, site/sensor changes, etc. Those rows
    opt out of the cross-source partial unique index (which is defined
    ``WHERE dedupe_hash IS NOT NULL``), exactly like the pre-migration
    rows whose hash was never computed.

    ``event_type`` accepts either a :class:`PumpEventType` enum or its
    bare ``.value`` string; both hash identically.

    Non-finite ``units`` (``inf`` / ``nan``) also return ``None`` -- such a
    value is nonsensical for an insulin delivery and would otherwise raise
    ``decimal.InvalidOperation`` in the quantizer. The row still persists via
    its natural key; it simply opts out of cross-source dedupe. Client input
    is additionally rejected at the schema boundary (see ``PumpEventPushItem``).

    Only insulin-DELIVERY event types (bolus / correction / combo_bolus /
    basal) are hashed; telemetry events that also carry ``units`` (RESERVOIR,
    BATTERY) return ``None`` so distinct status snapshots aren't collapsed.
    """
    if units is None or not math.isfinite(units):
        return None

    type_value = getattr(event_type, "value", event_type)
    if type_value not in _DELIVERY_EVENT_TYPE_VALUES:
        return None

    ts_bucket = _round_to_bucket(event_timestamp)
    units_q = Decimal(str(units)).quantize(_UNIT_QUANTUM, rounding=ROUND_HALF_UP)
    duration = duration_minutes or 0

    payload = f"{user_id}|{type_value}|{ts_bucket}|{units_q}|{duration}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _round_to_bucket(ts: datetime) -> int:
    """Round a timestamp to the nearest 30-second epoch boundary.

    Naive datetimes are treated as UTC so the bucket is deterministic
    regardless of the writer's timezone handling.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    epoch = Decimal(str(ts.timestamp()))
    buckets = (epoch / _TIME_BUCKET_SECONDS).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(buckets) * _TIME_BUCKET_SECONDS
