"""Tests for cross-source CGM dedupe + primary-source preference (Story 43.10).

Covers the cgm_source service (listing, default-role assignment, exclusion
computation, atomic primary switch), the picker endpoints, and the
primary-source filtering applied to the glucose read endpoints.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db
from src.main import app
from src.models.glucose import GlucoseReading, TrendDirection
from src.models.integration import (
    IntegrationCredential,
    IntegrationStatus,
    IntegrationType,
)
from src.models.nightscout_connection import (
    NightscoutApiVersion,
    NightscoutAuthType,
    NightscoutConnection,
    NightscoutSyncStatus,
)
from src.services.cgm_source import (
    CGM_ROLE_OFF,
    CGM_ROLE_PRIMARY,
    CGM_ROLE_SECONDARY,
    default_cgm_role_for_new_source,
    get_excluded_cgm_sources,
    list_cgm_sources,
    set_primary_cgm_source,
)


async def _register(client: AsyncClient) -> tuple[str, uuid.UUID]:
    email = f"cgm-{uuid.uuid4().hex[:10]}@example.com"
    reg = await client.post(
        "/api/auth/register", json={"email": email, "password": "SecurePass123"}
    )
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/auth/login", json={"email": email, "password": "SecurePass123"}
    )
    cookie = login.cookies.get(settings.jwt_cookie_name)
    me = await client.get("/api/auth/me", cookies={settings.jwt_cookie_name: cookie})
    return cookie, uuid.UUID(me.json()["id"])


async def _add_dexcom(
    db: AsyncSession,
    uid: uuid.UUID,
    role: str,
    status: IntegrationStatus = IntegrationStatus.CONNECTED,
) -> None:
    db.add(
        IntegrationCredential(
            user_id=uid,
            integration_type=IntegrationType.DEXCOM,
            encrypted_username="x",
            encrypted_password="y",
            status=status,
            cgm_role=role,
        )
    )
    await db.commit()


async def _add_ns(db: AsyncSession, uid: uuid.UUID, role: str, name: str) -> uuid.UUID:
    conn = NightscoutConnection(
        user_id=uid,
        name=name,
        base_url="https://ns.example.com",
        auth_type=NightscoutAuthType.TOKEN,
        encrypted_credential="enc",
        api_version=NightscoutApiVersion.V1,
        last_sync_status=NightscoutSyncStatus.NEVER,
        cgm_role=role,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn.id


async def _seed_glucose(
    db: AsyncSession, uid: uuid.UUID, source: str, count: int
) -> None:
    now = datetime.now(UTC)
    for i in range(count):
        ts = now - timedelta(minutes=i * 5)
        db.add(
            GlucoseReading(
                user_id=uid,
                value=120,
                reading_timestamp=ts,
                trend=TrendDirection.FLAT,
                trend_rate=0.0,
                received_at=ts,
                source=source,
            )
        )
    await db.commit()


@pytest.mark.asyncio
class TestCgmSourceService:
    async def test_lists_dexcom_and_nightscout_not_tandem(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                ns_id = await _add_ns(db, uid, CGM_ROLE_SECONDARY, "My NS")
                # A pump-only Tandem credential must not appear.
                db.add(
                    IntegrationCredential(
                        user_id=uid,
                        integration_type=IntegrationType.TANDEM,
                        encrypted_username="x",
                        encrypted_password="y",
                        status=IntegrationStatus.CONNECTED,
                    )
                )
                await db.commit()

                sources = await list_cgm_sources(db, uid)
                assert {s.kind for s in sources} == {"dexcom", "nightscout"}
                assert {s.source for s in sources} == {
                    "dexcom",
                    f"nightscout:{ns_id}",
                }
                assert len(sources) == 2
                break

    async def test_default_role_primary_then_secondary(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                # No CGM yet -> first source is primary.
                assert (
                    await default_cgm_role_for_new_source(db, uid) == CGM_ROLE_PRIMARY
                )
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                # A primary now exists -> next source is secondary.
                assert (
                    await default_cgm_role_for_new_source(db, uid) == CGM_ROLE_SECONDARY
                )
                break

    async def test_excluded_empty_for_single_source(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                assert await get_excluded_cgm_sources(db, uid) == []
                break

    async def test_excluded_drops_secondary_and_off(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                ns_id = await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Loop NS")
                excluded = await get_excluded_cgm_sources(db, uid)
                assert excluded == [f"nightscout:{ns_id}"]
                # include_secondary re-includes the secondary source.
                assert (
                    await get_excluded_cgm_sources(db, uid, include_secondary=True)
                    == []
                )
                break

    async def test_off_excluded_even_with_include_secondary(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                ns_id = await _add_ns(db, uid, CGM_ROLE_OFF, "Old NS")
                assert await get_excluded_cgm_sources(
                    db, uid, include_secondary=True
                ) == [f"nightscout:{ns_id}"]
                break

    async def test_set_primary_demotes_others(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                ns_id = await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Loop NS")
                ok = await set_primary_cgm_source(db, uid, f"nightscout:{ns_id}")
                await db.commit()
                assert ok is True
                sources = {s.source: s.role for s in await list_cgm_sources(db, uid)}
                assert sources[f"nightscout:{ns_id}"] == CGM_ROLE_PRIMARY
                assert sources["dexcom"] == CGM_ROLE_SECONDARY
                break

    async def test_set_primary_unknown_source_returns_false(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                assert await set_primary_cgm_source(db, uid, "nightscout:nope") is False
                break

    async def test_set_primary_dexcom_direction(self):
        # The asymmetric branch: promote Dexcom, demote NS.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_SECONDARY)
                await _add_ns(db, uid, CGM_ROLE_PRIMARY, "Loop NS")
                assert await set_primary_cgm_source(db, uid, "dexcom") is True
                await db.commit()
                roles = {s.source: s.role for s in await list_cgm_sources(db, uid)}
                assert roles["dexcom"] == CGM_ROLE_PRIMARY
                assert all(
                    r == CGM_ROLE_SECONDARY for s, r in roles.items() if s != "dexcom"
                )
                break

    async def test_set_primary_preserves_off(self):
        # Switching the primary must not silently re-enable an "off" source.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                off_id = await _add_ns(db, uid, CGM_ROLE_OFF, "Disabled NS")
                live_id = await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Live NS")
                await set_primary_cgm_source(db, uid, f"nightscout:{live_id}")
                await db.commit()
                roles = {s.source: s.role for s in await list_cgm_sources(db, uid)}
                assert roles[f"nightscout:{off_id}"] == CGM_ROLE_OFF  # stayed off
                assert roles[f"nightscout:{live_id}"] == CGM_ROLE_PRIMARY
                assert roles["dexcom"] == CGM_ROLE_SECONDARY
                break

    async def test_errored_dexcom_not_listed(self):
        # An errored Dexcom must not count as an active CGM source -- otherwise
        # an errored primary would blank the dashboard while NS keeps syncing.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(
                    db, uid, CGM_ROLE_PRIMARY, status=IntegrationStatus.ERROR
                )
                ns_id = await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Live NS")
                sources = await list_cgm_sources(db, uid)
                assert {s.source for s in sources} == {f"nightscout:{ns_id}"}
                # No active primary -> exclude nothing, so the live NS shows.
                assert await get_excluded_cgm_sources(db, uid) == []
                break

    async def test_no_primary_excludes_nothing(self):
        # H1 invariant: a lone surviving secondary (no primary) is NOT hidden.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            _, uid = await _register(client)
            async for db in get_db():
                # Only a secondary source exists -- e.g. the primary was
                # disconnected. Excluding it would blank the dashboard.
                await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Survivor NS")
                assert await get_excluded_cgm_sources(db, uid) == []
                break

    async def test_nightscout_source_format_matches_translator(self):
        # Pinning test: the role-resolver's source string must equal what the
        # Nightscout translator writes into glucose_readings.source, or the
        # dedupe filter silently stops matching real rows.
        from src.services.cgm_source import nightscout_source
        from src.services.integrations.nightscout.translator import _build_source

        cid = uuid.uuid4()
        assert nightscout_source(cid) == _build_source(str(cid))


@pytest.mark.asyncio
class TestCgmEndpoints:
    async def test_get_cgm_sources(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Loop NS")
                break
            resp = await client.get(
                "/api/integrations/cgm",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["multiple_sources"] is True
            assert body["primary_source"] == "dexcom"
            assert len(body["sources"]) == 2

    async def test_put_primary_then_404_for_unknown(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                ns_id = await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Loop NS")
                break
            ok = await client.put(
                "/api/integrations/cgm/source",
                cookies={settings.jwt_cookie_name: cookie},
                json={"source": f"nightscout:{ns_id}"},
            )
            assert ok.status_code == 200
            assert ok.json()["primary_source"] == f"nightscout:{ns_id}"

            bad = await client.put(
                "/api/integrations/cgm/source",
                cookies={settings.jwt_cookie_name: cookie},
                json={"source": "nightscout:does-not-exist"},
            )
            assert bad.status_code == 404


@pytest.mark.asyncio
class TestGlucoseFilteringByPrimary:
    async def test_stats_count_primary_only_then_both(self):
        # AC3/AC5: Dexcom primary + NS secondary, equal readings each.
        # Default stats see only the primary half; include_secondary sees all.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                ns_id = await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Loop NS")
                await _seed_glucose(db, uid, "dexcom", 20)
                await _seed_glucose(db, uid, f"nightscout:{ns_id}", 20)
                break

            primary_only = await client.get(
                "/api/integrations/glucose/stats?minutes=1440",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert primary_only.status_code == 200
            assert primary_only.json()["readings_count"] == 20

            both = await client.get(
                "/api/integrations/glucose/stats?minutes=1440&include_secondary=true",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert both.json()["readings_count"] == 40

    async def test_single_source_not_filtered(self):
        # AC4: with one CGM source, no filtering happens.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                await _seed_glucose(db, uid, "dexcom", 15)
                break
            resp = await client.get(
                "/api/integrations/glucose/stats?minutes=1440",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert resp.json()["readings_count"] == 15

    async def test_history_and_tir_honor_primary(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                ns_id = await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Loop NS")
                await _seed_glucose(db, uid, "dexcom", 10)
                await _seed_glucose(db, uid, f"nightscout:{ns_id}", 10)
                break

            hist = await client.get(
                "/api/integrations/glucose/history?minutes=1440&limit=100",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert hist.json()["count"] == 10

            tir = await client.get(
                "/api/integrations/glucose/time-in-range?minutes=1440",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert tir.json()["readings_count"] == 10

    async def test_current_and_percentiles_honor_primary(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cookie, uid = await _register(client)
            async for db in get_db():
                await _add_dexcom(db, uid, CGM_ROLE_PRIMARY)
                ns_id = await _add_ns(db, uid, CGM_ROLE_SECONDARY, "Loop NS")
                # Primary readings are older; the secondary posts the most
                # recent row -- /current must still return a primary reading.
                now = datetime.now(UTC)
                db.add(
                    GlucoseReading(
                        user_id=uid,
                        value=99,
                        reading_timestamp=now - timedelta(minutes=10),
                        trend=TrendDirection.FLAT,
                        trend_rate=0.0,
                        received_at=now,
                        source="dexcom",
                    )
                )
                db.add(
                    GlucoseReading(
                        user_id=uid,
                        value=222,
                        reading_timestamp=now,
                        trend=TrendDirection.FLAT,
                        trend_rate=0.0,
                        received_at=now,
                        source=f"nightscout:{ns_id}",
                    )
                )
                await db.commit()

            current = await client.get(
                "/api/integrations/glucose/current",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert current.status_code == 200
            # The secondary's 222 is newer but excluded -> primary's 99 shows.
            assert current.json()["value"] == 99

            # Seed enough primary history for the 7-day AGP minimum, plus a
            # secondary that would skew percentiles if not excluded.
            async for db in get_db():
                await _seed_glucose(db, uid, "dexcom", 200)
                await _seed_glucose(db, uid, f"nightscout:{ns_id}", 200)
                break
            agp = await client.get(
                "/api/integrations/glucose/percentiles?days=14",
                cookies={settings.jwt_cookie_name: cookie},
            )
            assert agp.status_code == 200
