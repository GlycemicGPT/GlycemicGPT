"""Unit + integration tests for `loop_state_extractor`.

Story 43.12 PR 6. Three things to pin:

1. **State-machine correctness per source engine** — `_extract_loop_status`
   classifies looping / not_looping / failed per the Loop and OpenAPS
   wire formats. This is the core projection.
2. **Override extraction** — `_extract_override` only fires when Loop's
   `loop.override.active == true`, and pulls the right fields out of
   the canonical shape.
3. **Staleness suppression** — `get_latest_loop_state` returns
   `loop_status=None` when the snapshot is older than the threshold,
   even though `cob_grams` continues through.

DB integration tests use a per-test user + clean-up like the other
test files in this codebase.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.encryption import encrypt_credential
from src.database import get_session_maker
from src.models.device_status_snapshot import DeviceStatusSnapshot
from src.models.nightscout_connection import (
    NightscoutAuthType,
    NightscoutConnection,
)
from src.models.user import User
from src.services.loop_state_extractor import (
    LoopStatus,
    OverrideStatus,
    _extract_loop_status,
    _extract_loop_status_from_loop_subtree,
    _extract_loop_status_from_openaps_subtree,
    _extract_override,
    get_latest_loop_state,
)

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def loop_ctx() -> AsyncGenerator[tuple[AsyncSession, uuid.UUID, uuid.UUID], None]:
    """Per-test session + fresh user + NS connection.

    `device_status_snapshots.nightscout_connection_id` is NOT NULL, so
    every test needs a connection row to attach snapshots to. Cleans
    up snapshots, connection, and user on teardown so cross-test
    leakage can't flip the latest-snapshot query result.

    Unlike PR 2's translator fixture, this one does NOT pre-yield
    TRUNCATE `forecast_snapshots` (and doesn't need an analogous
    TRUNCATE on `device_status_snapshots`). The query path is
    user-scoped (`WHERE user_id = ...`) and each test gets a fresh
    user_id, so other tests' snapshot rows for OTHER users can't
    influence the latest-snapshot read. Per-connection uniqueness
    (`ns_id`) is local because each test creates its own connection.
    """
    session_maker = get_session_maker()
    session = session_maker()
    email = f"loop_state_{uuid.uuid4().hex[:10]}@example.com"
    user = User(email=email, hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()
    user_id = user.id

    conn = NightscoutConnection(
        user_id=user_id,
        name="test-loop-state",
        base_url="https://example.com",
        auth_type=NightscoutAuthType.SECRET,
        encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
        initial_sync_window_days=7,
    )
    session.add(conn)
    await session.flush()
    connection_id = conn.id
    await session.commit()

    try:
        yield session, user_id, connection_id
    finally:
        try:
            await session.rollback()
            await session.execute(
                delete(DeviceStatusSnapshot).where(
                    DeviceStatusSnapshot.user_id == user_id
                )
            )
            # Delete ALL connections for the test user, not just the
            # fixture-yielded one. The multi-connection test
            # `test_latest_snapshot_wins_across_connections` creates
            # an additional connection; cleaning up by user_id covers
            # it without per-test cleanup boilerplate.
            await session.execute(
                delete(NightscoutConnection).where(
                    NightscoutConnection.user_id == user_id
                )
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        except RuntimeError:
            pass
        finally:
            try:
                await session.close()
            except RuntimeError:
                pass


def _make_snapshot(
    user_id: uuid.UUID,
    *,
    snapshot_timestamp: datetime,
    connection_id: uuid.UUID | None = None,
    loop_subtree: dict | None = None,
    openaps_subtree: dict | None = None,
    cob_grams: float | None = None,
    source_device: str | None = None,
) -> DeviceStatusSnapshot:
    """Build a DeviceStatusSnapshot for tests. ns_id is randomized to
    avoid colliding with the per-connection uniqueness constraint.
    Pure-function tests pass `connection_id=None` to skip DB writes;
    DB tests pass the fixture's connection_id so the FK satisfies the
    NOT NULL constraint."""
    return DeviceStatusSnapshot(
        user_id=user_id,
        nightscout_connection_id=connection_id,
        snapshot_timestamp=snapshot_timestamp,
        received_at=datetime.now(UTC),
        source_uploader=None,
        source_device=source_device,
        ns_id=f"test_{uuid.uuid4().hex}",
        iob_units=None,
        cob_grams=cob_grams,
        pump_battery_percent=None,
        pump_reservoir_units=None,
        pump_suspended=None,
        loop_failure_reason=None,
        loop_subtree_json=loop_subtree,
        openaps_subtree_json=openaps_subtree,
        pump_subtree_json=None,
        uploader_subtree_json=None,
    )


# ---------------------------------------------------------------------------
# Pure-function tests: loop status state machine
# ---------------------------------------------------------------------------


class TestLoopStatusFromLoopSubtree:
    """`loop.{failureReason,enacted,suggested}` -> state machine.

    Loop is the simpler path because the `failureReason` field is a
    discrete signal not present in the OpenAPS wire format.
    """

    def test_failure_reason_classifies_as_failed(self):
        issued = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
        status = _extract_loop_status_from_loop_subtree(
            {"failureReason": "Glucose data is unavailable"},
            issued_at=issued,
        )
        assert status is not None
        assert status.state == "failed"
        assert status.failure_reason == "Glucose data is unavailable"
        assert status.source == "loop"
        assert status.issued_at == issued

    def test_enacted_subtree_classifies_as_looping(self):
        status = _extract_loop_status_from_loop_subtree(
            {"enacted": {"timestamp": "2026-05-13T12:00:00Z"}},
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is not None
        assert status.state == "looping"
        assert status.failure_reason is None

    def test_suggested_only_classifies_as_not_looping(self):
        """Suggested without enacted means the algorithm computed a
        suggestion but didn't act on it -- the canonical not-looping
        signal."""
        status = _extract_loop_status_from_loop_subtree(
            {"suggested": {"rate": 1.0}},
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is not None
        assert status.state == "not_looping"

    def test_empty_loop_subtree_returns_none(self):
        """No failureReason / enacted / suggested -> not a forecast-
        publishing cycle -> no badge."""
        status = _extract_loop_status_from_loop_subtree(
            {},
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is None

    def test_empty_string_failure_reason_does_not_trigger_failed(self):
        """Some uploaders emit `failureReason: ""` even when no failure
        occurred. Treat as if absent."""
        status = _extract_loop_status_from_loop_subtree(
            {"failureReason": "   ", "enacted": {"timestamp": "x"}},
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is not None
        assert status.state == "looping"

    def test_failed_wins_over_enacted(self):
        """A cycle that recorded both a failure AND an enacted block
        (rare but possible) is failed -- the failure is the stronger
        signal for the user."""
        status = _extract_loop_status_from_loop_subtree(
            {"failureReason": "Pump unreachable", "enacted": {"rate": 1.0}},
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is not None
        assert status.state == "failed"


class TestLoopStatusFromOpenapsSubtree:
    """`openaps.{enacted,suggested}` for AAPS / Trio / oref0 / iAPS.

    No failureReason equivalent in the OpenAPS wire format -- failures
    surface as not_looping with the explanation in `suggested.reason`
    text.
    """

    def test_aaps_enacted_classifies_as_looping_aaps(self):
        status = _extract_loop_status_from_openaps_subtree(
            {"enacted": {"rate": 1.0}},
            device="openaps://AndroidAPS",
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is not None
        assert status.state == "looping"
        assert status.source == "aaps"

    def test_aaps_suggested_only_classifies_as_not_looping(self):
        status = _extract_loop_status_from_openaps_subtree(
            {"suggested": {"reason": "in range"}},
            device="openaps://AndroidAPS",
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is not None
        assert status.state == "not_looping"
        assert status.source == "aaps"

    def test_oref0_device_uri_classifies_correctly(self):
        """oref0 uses `openaps://<host>/<pump-ref>` (two-segment URI),
        distinguished from AAPS's single-segment form."""
        status = _extract_loop_status_from_openaps_subtree(
            {"enacted": {}},
            device="openaps://edison-rig/medtronic-722",
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is not None
        assert status.source == "oref0"

    def test_iaps_substring_classifies_correctly(self):
        status = _extract_loop_status_from_openaps_subtree(
            {"enacted": {}},
            device="iAPS-2.7.0",
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is not None
        assert status.source == "iaps"

    def test_trio_via_determination_fallback(self):
        """Older Trio builds emit a `determination` block characteristic
        of Trio. When the device string doesn't classify (legacy NS
        bridges that strip the device field), the determination block
        is the fallback signal."""
        status = _extract_loop_status_from_openaps_subtree(
            {
                "determination": {},
                "enacted": {"rate": 1.0},
            },
            device="",  # No classifiable device string
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is not None
        assert status.source == "trio"

    def test_unknown_source_returns_none(self):
        """Indeterminate source -> no badge. Better to hide than
        mis-attribute."""
        status = _extract_loop_status_from_openaps_subtree(
            {"enacted": {"rate": 1.0}},
            device="some-future-uploader",
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is None

    def test_empty_openaps_subtree_returns_none(self):
        """No enacted, no suggested -> nothing to report."""
        status = _extract_loop_status_from_openaps_subtree(
            {},
            device="openaps://AndroidAPS",
            issued_at=datetime(2026, 5, 13, 12, 0, tzinfo=UTC),
        )
        assert status is None


class TestLoopStatusRouting:
    """`_extract_loop_status` picks Loop > OpenAPS when both present.

    Same priority as the forecast mapper (PR 2) -- Loop's subtree
    presence is unambiguous and wins over the OpenAPS fallback path.
    """

    def test_loop_subtree_wins_over_openaps(self):
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={"enacted": {}},
            openaps_subtree={"suggested": {"reason": "stale"}},
            source_device="loop://iPhone",
        )
        status = _extract_loop_status(ds)
        assert status is not None
        assert status.source == "loop"
        assert status.state == "looping"

    def test_no_subtree_returns_none(self):
        """xDrip+ / CGM-only relays publish neither -> no badge."""
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
        )
        assert _extract_loop_status(ds) is None


# ---------------------------------------------------------------------------
# Override extractor (Loop-only in PR 6)
# ---------------------------------------------------------------------------


class TestOverrideExtractor:
    """Loop's `loop.override.{active,name,timestamp,duration,multiplier,
    currentCorrectionRange}` -> OverrideStatus. AAPS / Trio override
    paths are deferred."""

    def test_active_override_extracts_all_fields(self):
        # Pin `now` to one minute past the override start so the
        # past-end / future-start guards both pass. Tests need to
        # inject `now` whenever they use hardcoded timestamps so the
        # guards don't reject as time passes.
        now = datetime(2026, 5, 13, 14, 1, tzinfo=UTC)
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Pre-meal",
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 1800,
                    "multiplier": 0.7,
                    "currentCorrectionRange": {
                        "minValue": 70,
                        "maxValue": 90,
                    },
                }
            },
        )
        override = _extract_override(ds, now=now)
        assert override is not None
        assert override.name == "Pre-meal"
        assert override.started_at == datetime(2026, 5, 13, 14, 0, tzinfo=UTC)
        # duration is SECONDS in Loop's wire format -> ends_at is +30 min
        assert override.ends_at == datetime(2026, 5, 13, 14, 30, tzinfo=UTC)
        assert override.multiplier == 0.7
        assert override.target_low_mgdl == 70.0
        assert override.target_high_mgdl == 90.0

    def test_inactive_override_returns_none(self):
        """`active: false` means the override has expired or was
        cancelled. Most common shape in production payloads -- Loop
        keeps emitting the most recent override even after it ends."""
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": False,
                    "name": "Pre-meal",
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 1800,
                }
            },
        )
        assert _extract_override(ds) is None

    def test_indefinite_override_has_no_end(self):
        """Loop encodes indefinite overrides as `duration: 0`. The
        UI should render "ongoing" rather than computing a phantom
        end time."""
        now = datetime(2026, 5, 13, 14, 1, tzinfo=UTC)
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Workout",
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 0,
                }
            },
        )
        override = _extract_override(ds, now=now)
        assert override is not None
        assert override.ends_at is None

    def test_missing_optional_fields_pass_as_none(self):
        """`multiplier` and `currentCorrectionRange` are optional in
        Loop's wire format. Their absence is normal, not malformed."""
        now = datetime(2026, 5, 13, 22, 1, tzinfo=UTC)
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Sleep",
                    "timestamp": "2026-05-13T22:00:00Z",
                    "duration": 28800,
                }
            },
        )
        override = _extract_override(ds, now=now)
        assert override is not None
        assert override.multiplier is None
        assert override.target_low_mgdl is None
        assert override.target_high_mgdl is None

    def test_missing_name_returns_none(self):
        """Without a name we have nothing to render -- skip."""
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 1800,
                }
            },
        )
        assert _extract_override(ds) is None

    def test_no_loop_subtree_returns_none(self):
        """AAPS-only user -- no Loop override path. Returns None for
        now; AAPS overrides come from Temp Target treatments, not
        devicestatus, and are deferred to a follow-up PR."""
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            openaps_subtree={"suggested": {"reason": "in range"}},
        )
        assert _extract_override(ds) is None

    def test_bool_multiplier_rejected(self):
        """`isinstance(True, int)` is True in Python; reject explicitly."""
        now = datetime(2026, 5, 13, 14, 1, tzinfo=UTC)
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Pre-meal",
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 1800,
                    "multiplier": True,  # bogus
                }
            },
        )
        override = _extract_override(ds, now=now)
        assert override is not None
        assert override.multiplier is None


# ---------------------------------------------------------------------------
# DB integration: staleness + COB pass-through + multi-snapshot ordering
# ---------------------------------------------------------------------------


class TestGetLatestLoopState:
    @pytest.mark.asyncio
    async def test_no_snapshots_returns_all_none(self, loop_ctx):
        """User with no NS data gets a clean all-None bundle. The
        hero card renders zero new surfaces."""
        session, user_id, _conn_id = loop_ctx
        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is None
        assert bundle.override is None
        assert bundle.cob_grams is None

    @pytest.mark.asyncio
    async def test_fresh_snapshot_populates_loop_status(self, loop_ctx):
        session, user_id, conn_id = loop_ctx
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=2),
            loop_subtree={"enacted": {"rate": 1.0}},
            source_device="loop://iPhone",
            cob_grams=24.0,
        )
        session.add(snap)
        await session.commit()

        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is not None
        assert bundle.loop_status.state == "looping"
        assert bundle.loop_status.source == "loop"
        assert bundle.cob_grams == 24.0

    @pytest.mark.asyncio
    async def test_stale_snapshot_suppresses_loop_status_only(self, loop_ctx):
        """Beyond 15 min the loop_status badge would be lying ("Looping"
        for a loop that may have stopped). Suppress the badge but keep
        COB numeric -- a stale COB at the boundary is informationally
        useful, not misleading."""
        session, user_id, conn_id = loop_ctx
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=20),
            loop_subtree={"enacted": {"rate": 1.0}},
            source_device="loop://iPhone",
            cob_grams=12.0,
        )
        session.add(snap)
        await session.commit()

        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is None
        assert bundle.cob_grams == 12.0  # preserved across the staleness boundary

    @pytest.mark.asyncio
    async def test_latest_by_snapshot_timestamp_not_received_at(self, loop_ctx):
        """Order by snapshot_timestamp DESC, not received_at. A backfill
        landing a 6-hour-old snapshot must not outrank a real-time one
        just because it was synced more recently."""
        session, user_id, conn_id = loop_ctx
        # Older snapshot received recently (backfill scenario)
        old_snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(hours=3),
            loop_subtree={"failureReason": "Old failure"},
            source_device="loop://iPhone",
        )
        old_snap.received_at = datetime.now(UTC)
        # Newer real-time snapshot
        new_snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=2),
            loop_subtree={"enacted": {"rate": 1.0}},
            source_device="loop://iPhone",
        )
        new_snap.received_at = datetime.now(UTC) - timedelta(minutes=1)
        session.add_all([old_snap, new_snap])
        await session.commit()

        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is not None
        # The newer snapshot's state wins -- looping, not failed.
        assert bundle.loop_status.state == "looping"

    @pytest.mark.asyncio
    async def test_active_override_surfaces(self, loop_ctx):
        session, user_id, conn_id = loop_ctx
        # Use a relative `started` so the past-end guard doesn't
        # reject the override based on test-run wall-clock time. 5
        # min ago + 60 min duration -> still active for ~55 min.
        started = datetime.now(UTC) - timedelta(minutes=5)
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=1),
            loop_subtree={
                "enacted": {"rate": 1.0},
                "override": {
                    "active": True,
                    "name": "Workout",
                    "timestamp": started.isoformat(),
                    "duration": 3600,
                    "multiplier": 0.5,
                },
            },
            source_device="loop://iPhone",
        )
        session.add(snap)
        await session.commit()

        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.override is not None
        assert bundle.override.name == "Workout"
        assert bundle.override.multiplier == 0.5

    @pytest.mark.asyncio
    async def test_cgm_only_snapshot_yields_no_loop_status(self, loop_ctx):
        """xDrip+ regression guard: a payload with only uploader battery
        and no loop/openaps subtree returns no loop_status even though
        a snapshot row exists."""
        session, user_id, conn_id = loop_ctx
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC),
            source_device="xdrip-android",
        )
        snap.uploader_subtree_json = {"battery": 80}
        session.add(snap)
        await session.commit()

        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is None
        assert bundle.override is None
        assert bundle.cob_grams is None

    @pytest.mark.asyncio
    async def test_loop_failure_surfaces_reason(self, loop_ctx):
        session, user_id, conn_id = loop_ctx
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=3),
            loop_subtree={"failureReason": "Glucose data is unavailable"},
            source_device="loop://iPhone",
        )
        session.add(snap)
        await session.commit()

        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is not None
        assert bundle.loop_status.state == "failed"
        assert bundle.loop_status.failure_reason == "Glucose data is unavailable"


# ---------------------------------------------------------------------------
# Smoke test for the dataclasses (frozen / immutable)
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_loop_status_is_frozen(self):
        """Frozen dataclasses keep the API neutral -- the projection
        consumer can't accidentally mutate the bundle and confuse the
        next consumer."""
        s = LoopStatus(
            state="looping",
            source="loop",
            issued_at=datetime.now(UTC),
        )
        with pytest.raises(Exception):  # noqa: B017 (FrozenInstanceError)
            s.state = "failed"  # type: ignore[misc]

    def test_override_status_is_frozen(self):
        o = OverrideStatus(
            name="Pre-meal",
            started_at=datetime.now(UTC),
        )
        with pytest.raises(Exception):  # noqa: B017
            o.name = "Workout"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Adversarial-review follow-up: bounds, future-clock, multi-connection
# ---------------------------------------------------------------------------


class TestLoopStateBoundsAndClockSkew:
    """Pins the defensive guards added in response to PR 6's
    adversarial review. Three classes of concern: free-text length
    bounds, future-dated timestamps from upstream clock skew, and
    past-end overrides that NS hasn't flipped to inactive yet.
    """

    @pytest.mark.asyncio
    async def test_failure_reason_capped_at_boundary(self, loop_ctx):
        """A malicious / buggy NS server posts a giant failureReason.
        The mapper must truncate at the extractor so the badge
        tooltip stays usable and the response payload bounded."""
        session, user_id, conn_id = loop_ctx
        huge = "A" * 5000
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=1),
            loop_subtree={"failureReason": huge},
            source_device="loop://iPhone",
        )
        session.add(snap)
        await session.commit()
        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is not None
        assert bundle.loop_status.state == "failed"
        # 200-char cap. The reason itself is `A * 5000`; truncated
        # form keeps the surface bounded for the UI.
        assert bundle.loop_status.failure_reason is not None
        assert len(bundle.loop_status.failure_reason) <= 200

    @pytest.mark.asyncio
    async def test_override_name_capped_at_boundary(self, loop_ctx):
        """Same DoS-shield rule for override names, which flow into
        the same `title` tooltip path."""
        session, user_id, conn_id = loop_ctx
        huge_name = "Override-" + ("X" * 2000)
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=1),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": huge_name,
                    "timestamp": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
                    "duration": 3600,
                }
            },
            source_device="loop://iPhone",
        )
        session.add(snap)
        await session.commit()
        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.override is not None
        assert len(bundle.override.name) <= 80

    @pytest.mark.asyncio
    async def test_future_snapshot_suppresses_loop_status(self, loop_ctx):
        """An uploader with a clock set 10 min in the future would
        post `created_at` ahead of now. Naive staleness math
        (`now - ts > 15 min`) returns False because the delta is
        negative; the badge would render claims from the future.
        Guard: reject loop_status when the snapshot leads now by
        more than the future-tolerance margin."""
        session, user_id, conn_id = loop_ctx
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) + timedelta(minutes=10),
            loop_subtree={"enacted": {"rate": 1.0}},
            source_device="loop://iPhone",
            cob_grams=18.0,
        )
        session.add(snap)
        await session.commit()
        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is None
        # COB stays numeric -- a stale-direction-future cob value is
        # data, not a state claim, and follows the same policy as the
        # past-stale path (cob preserved, loop_status suppressed).
        assert bundle.cob_grams == 18.0

    @pytest.mark.asyncio
    async def test_near_future_snapshot_still_accepted(self, loop_ctx):
        """Ordinary millisecond-scale clock skew between the user's
        phone and our server should NOT suppress the badge.
        Snapshots within the 2-min future tolerance pass through."""
        session, user_id, conn_id = loop_ctx
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) + timedelta(seconds=30),
            loop_subtree={"enacted": {"rate": 1.0}},
            source_device="loop://iPhone",
        )
        session.add(snap)
        await session.commit()
        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is not None
        assert bundle.loop_status.state == "looping"

    @pytest.mark.asyncio
    async def test_past_end_override_suppressed(self, loop_ctx):
        """A stale snapshot carrying `active: true` for an override
        whose end time is already in the past. The frontend's
        formatter renders "ongoing" in that case which would lie;
        the server-side guard suppresses the override entirely."""
        session, user_id, conn_id = loop_ctx
        # Override started 2h ago with 30 min duration -> ended 1h30m ago
        started = datetime.now(UTC) - timedelta(hours=2)
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=1),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Pre-meal",
                    "timestamp": started.isoformat(),
                    "duration": 1800,  # 30 min in seconds
                }
            },
            source_device="loop://iPhone",
        )
        session.add(snap)
        await session.commit()
        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.override is None

    @pytest.mark.asyncio
    async def test_future_start_override_suppressed(self, loop_ctx):
        """Symmetric to the past-end case: an override whose
        `started_at` is in the future (uploader clock skew). We can't
        honestly claim an override is running before its start time."""
        session, user_id, conn_id = loop_ctx
        started_future = datetime.now(UTC) + timedelta(minutes=30)
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=1),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Workout",
                    "timestamp": started_future.isoformat(),
                    "duration": 3600,
                }
            },
            source_device="loop://iPhone",
        )
        session.add(snap)
        await session.commit()
        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.override is None

    @pytest.mark.asyncio
    async def test_indefinite_override_with_recent_start_accepted(self, loop_ctx):
        """Indefinite overrides (duration=0) have ends_at=None; the
        past-end guard must NOT fire when ends_at is None. Regression
        guard against an over-eager `ends_at < now` check."""
        session, user_id, conn_id = loop_ctx
        started = datetime.now(UTC) - timedelta(minutes=5)
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=1),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Workout",
                    "timestamp": started.isoformat(),
                    "duration": 0,  # indefinite
                }
            },
            source_device="loop://iPhone",
        )
        session.add(snap)
        await session.commit()
        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.override is not None
        assert bundle.override.ends_at is None


class TestMultiConnectionLatestSnapshot:
    """Pins the current LRU-style multi-connection behavior so a
    future refactor (e.g., wiring to Story 43.10's primary-source
    picker) can't silently change it without test pressure.
    """

    @pytest.mark.asyncio
    async def test_latest_snapshot_wins_across_connections(self, loop_ctx):
        """User has TWO NS connections (rare but possible -- e.g.,
        Loop on connection A and AAPS on connection B). The
        latest-by-snapshot-timestamp row determines the badge.
        Documented LRU; replace with primary-source preference in
        43.10."""
        session, user_id, conn_a = loop_ctx
        # Create a second NS connection for the same user.
        conn_b_row = NightscoutConnection(
            user_id=user_id,
            name="test-loop-state-2",
            base_url="https://example2.com",
            auth_type=NightscoutAuthType.SECRET,
            encrypted_credential=encrypt_credential("test-secret-min-12-chars"),
            initial_sync_window_days=7,
        )
        session.add(conn_b_row)
        await session.flush()
        conn_b = conn_b_row.id

        # Connection A: Loop, snapshot 3 min ago
        snap_a = _make_snapshot(
            user_id,
            connection_id=conn_a,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=3),
            loop_subtree={"enacted": {"rate": 1.0}},
            source_device="loop://iPhone",
        )
        # Connection B: AAPS, snapshot 1 min ago (newer)
        snap_b = _make_snapshot(
            user_id,
            connection_id=conn_b,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=1),
            openaps_subtree={"enacted": {"rate": 1.2}},
            source_device="openaps://AndroidAPS",
        )
        session.add_all([snap_a, snap_b])
        await session.commit()

        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.loop_status is not None
        # AAPS wins because its snapshot is newer.
        assert bundle.loop_status.source == "aaps"


class TestMedicalFieldBounds:
    """Pins the extractor-level clamps for medical-adjacent fields.
    Out-of-range values fail soft (drop the field, keep the rest of
    the override / bundle renderable) rather than 500-ing the whole
    /pump/status response.
    """

    def test_out_of_range_multiplier_dropped(self):
        """A `multiplier` outside [0.05, 10.0] is a serialization bug
        or an absurd value -- drop it but keep the override's
        name/timestamps so the user still sees the override running."""
        now = datetime(2026, 5, 13, 14, 1, tzinfo=UTC)
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Pre-meal",
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 1800,
                    "multiplier": 100.0,  # absurd
                }
            },
        )
        override = _extract_override(ds, now=now)
        assert override is not None
        assert override.name == "Pre-meal"  # rest of override intact
        assert override.multiplier is None  # bad numeric dropped

    def test_zero_multiplier_dropped(self):
        """Below the 0.05 floor -- catches the common NaN-serialized-
        as-0 bug."""
        now = datetime(2026, 5, 13, 14, 1, tzinfo=UTC)
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Pre-meal",
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 1800,
                    "multiplier": 0.0,
                }
            },
        )
        override = _extract_override(ds, now=now)
        assert override is not None
        assert override.multiplier is None

    def test_out_of_range_targets_dropped(self):
        """Target values outside the physiological band are dropped."""
        now = datetime(2026, 5, 13, 14, 1, tzinfo=UTC)
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Pre-meal",
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 1800,
                    "currentCorrectionRange": {
                        "minValue": -100,  # impossible
                        "maxValue": 9999,  # impossible
                    },
                }
            },
        )
        override = _extract_override(ds, now=now)
        assert override is not None
        assert override.target_low_mgdl is None
        assert override.target_high_mgdl is None

    def test_inverted_target_band_dropped(self):
        """If target_low > target_high after parsing, the band is
        inverted -- drop both rather than render a confused tooltip."""
        now = datetime(2026, 5, 13, 14, 1, tzinfo=UTC)
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Pre-meal",
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 1800,
                    "currentCorrectionRange": {
                        "minValue": 120,
                        "maxValue": 80,  # inverted
                    },
                }
            },
        )
        override = _extract_override(ds, now=now)
        assert override is not None
        assert override.target_low_mgdl is None
        assert override.target_high_mgdl is None

    @pytest.mark.asyncio
    async def test_out_of_range_cob_clamped_to_none(self, loop_ctx):
        """A DB row with cob_grams = 9999 (impossible) drops to None
        on the bundle. The schema-layer Field(le=500) would 500 the
        endpoint; the extractor's clamp keeps the rest of the bundle
        renderable."""
        session, user_id, conn_id = loop_ctx
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=1),
            loop_subtree={"enacted": {"rate": 1.0}},
            source_device="loop://iPhone",
            cob_grams=9999.0,  # out-of-bounds
        )
        session.add(snap)
        await session.commit()
        bundle = await get_latest_loop_state(session, user_id)
        # loop_status still renders; cob is dropped.
        assert bundle.loop_status is not None
        assert bundle.cob_grams is None

    @pytest.mark.asyncio
    async def test_negative_cob_clamped_to_none(self, loop_ctx):
        """Negative carbs are impossible; same clamp policy."""
        session, user_id, conn_id = loop_ctx
        snap = _make_snapshot(
            user_id,
            connection_id=conn_id,
            snapshot_timestamp=datetime.now(UTC) - timedelta(minutes=1),
            cob_grams=-5.0,
            source_device="loop://iPhone",
            loop_subtree={"enacted": {"rate": 1.0}},
        )
        session.add(snap)
        await session.commit()
        bundle = await get_latest_loop_state(session, user_id)
        assert bundle.cob_grams is None


class TestOverrideDurationOverflowGuard:
    """Pins the duration clamp added in response to CR's PR-6 review.

    Without the clamp, a malicious or buggy NS uploader posting a
    pathological `duration` (e.g., `1e20`) raises `OverflowError`
    from `timedelta(seconds=...)`. That exception propagates out of
    `_extract_override`, into `get_latest_loop_state`, into the
    `/pump/status` handler, and 500s the hero card for that user
    until the snapshot ages out (15 min later).
    """

    def test_overflow_duration_dropped_not_raises(self):
        """`duration: 1e20` would overflow `timedelta` -> propagating
        OverflowError -> 500 on every /pump/status call. The clamp
        catches it before any timedelta arithmetic; the override is
        rendered indefinite (`ends_at=None`) while `name` / `started_at`
        stay intact. Same fail-soft policy as the multiplier / targets
        clamps -- bad numeric detail dropped, surrounding row renders."""
        now = datetime(2026, 5, 13, 14, 1, tzinfo=UTC)
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Pre-meal",
                    "timestamp": "2026-05-13T14:00:00Z",
                    "duration": 1e20,  # would overflow timedelta
                }
            },
        )
        # Critically: must not raise. The previous shape would have
        # produced an uncaught OverflowError out of /pump/status.
        override = _extract_override(ds, now=now)
        assert override is not None
        assert override.name == "Pre-meal"
        assert override.ends_at is None

    def test_seven_day_duration_accepted(self):
        """The 7-day ceiling is inclusive. Loop's UI caps at 24h, so
        7 days is generous; this test pins the boundary."""
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Extended workout",
                    "timestamp": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                    "duration": 7 * 24 * 3600,  # exactly at the cap
                }
            },
        )
        override = _extract_override(ds, now=datetime.now(UTC))
        assert override is not None
        assert override.ends_at is not None

    def test_eight_day_duration_rejected(self):
        """Past the 7-day ceiling -> clamp drops the duration; the
        override is rendered as indefinite (`ends_at = None`).
        Documented behavior: better to lose end-time precision than
        to risk overflow."""
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Marathon training",
                    "timestamp": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                    "duration": 8 * 24 * 3600,  # just past the cap
                }
            },
        )
        override = _extract_override(ds, now=datetime.now(UTC))
        assert override is not None
        assert override.ends_at is None  # cap-rejection drops to None

    def test_infinite_duration_dropped(self):
        """`+inf` and `NaN` both fail `<= max` -> override rendered
        indefinite. The previous shape would have produced
        ValueError from timedelta."""
        ds = _make_snapshot(
            uuid.uuid4(),
            snapshot_timestamp=datetime.now(UTC),
            loop_subtree={
                "override": {
                    "active": True,
                    "name": "Pre-meal",
                    "timestamp": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                    "duration": float("inf"),
                }
            },
        )
        override = _extract_override(ds, now=datetime.now(UTC))
        assert override is not None
        assert override.ends_at is None
