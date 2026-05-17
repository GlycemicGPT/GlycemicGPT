"""Story 16.6: Tandem cloud upload service.

Handles authenticating with Tandem via tconnectsync's OIDC PKCE flow,
building the upload payload (matching the official app's JSON schema),
HMAC-SHA1 signing, and POSTing data to the Tandem cloud so the
endocrinologist's portal stays updated.

Protocol reference: _bmad-output/planning-artifacts/tandem-reverse-engineering.md
"""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.core.encryption import decrypt_credential, encrypt_credential
from src.core.tandem_regions import (
    SUPPORTED_TANDEM_COUNTRIES,
    TandemLegacyRegionError,
    resolve_country_or_raise,
)
from src.logging_config import get_logger
from src.models.integration import (
    IntegrationCredential,
    IntegrationType,
)
from src.models.pump_hardware_info import PumpHardwareInfo
from src.models.pump_raw_event import PumpRawEvent
from src.models.tandem_upload_state import TandemUploadState

logger = get_logger(__name__)

__all__ = [
    "TandemLegacyRegionError",
    "build_upload_payload",
    "fetch_tandem_config",
    "get_last_event_uploaded",
    "reset_tandem_upload_state",
    "sign_tdc_token",
    "upload_to_tandem",
]


# HMAC-SHA1 signing key for the TDCToken header.
# This is a public protocol constant embedded in the official t:connect
# mobile app binary (com.tandemdiabetes.tconnect). It is NOT a user secret.
# The key is used as raw UTF-8 bytes (NOT base64-decoded).
_HMAC_KEY = b"1hvigLmZyCUBMQxn37SO7Iwn9EoTB1rBUBQg1CFyxcU="


# Upload limits
_MAX_EVENTS_PER_UPLOAD = 500
_UPLOAD_TIMEOUT_SECONDS = 60

# Endpoint config cache (TTL 24h)
_config_cache: dict[str, tuple[dict, datetime]] = {}
_CONFIG_TTL = timedelta(hours=24)


async def _lock_or_create_upload_state(
    db: AsyncSession, user_id: uuid.UUID
) -> TandemUploadState:
    """Return the TandemUploadState row for ``user_id`` with a row-level lock.

    Uses Postgres ``INSERT ... ON CONFLICT DO NOTHING`` to atomically
    materialize the row if it doesn't exist, then ``SELECT ... FOR UPDATE``
    to serialize against concurrent upload/reset calls. Without the upsert
    step, two concurrent first-time callers both observe "no row", both
    insert, and one fails the unique constraint on ``user_id``.

    The upsert commits its own transaction so subsequent FOR UPDATE has a
    row to lock; callers should not assume anything else is committed.
    """
    upsert = (
        pg_insert(TandemUploadState)
        .values(user_id=user_id, enabled=False)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    await db.execute(upsert)
    await db.commit()

    result = await db.execute(
        select(TandemUploadState)
        .where(TandemUploadState.user_id == user_id)
        .with_for_update()
    )
    state = result.scalar_one()
    return state


def sign_tdc_token(json_body_bytes: bytes, hmac_key: bytes | None = None) -> str:
    """Compute HMAC-SHA1 of the JSON body and return base64-encoded signature.

    This produces the value for the TDCToken header:
        TDCToken: token {return_value}
    """
    key = hmac_key or _HMAC_KEY
    signature = hmac.new(key, json_body_bytes, hashlib.sha1).digest()
    return base64.b64encode(signature).decode("ascii")


async def fetch_tandem_config(country: str = "US") -> dict:
    """Fetch dynamic endpoint configuration from Tandem's CDN.

    GET https://assets.tandemdiabetes.com/configuration/mobile-urls/{country}.json

    The CDN is keyed by ISO-3166 country code, not by cloud region. Probing
    on 2026-05-17 confirmed ``EU.json`` returns 404; ``GB.json``, ``DE.json``,
    ``CA.json``, ``AU.json`` etc. return 200. Each country file points at one
    of the two cloud backends (US or EU) -- see ``src.core.tandem_regions``.

    Caches the result for 24 hours per country.
    """
    if country not in SUPPORTED_TANDEM_COUNTRIES:
        raise ValueError(f"Unsupported Tandem country code: {country!r}")

    now = datetime.now(UTC)
    cached = _config_cache.get(country)
    if cached and (now - cached[1]) < _CONFIG_TTL:
        return cached[0]

    config_base = settings.tandem_upload_config_base
    url = f"{config_base}/configuration/mobile-urls/{country}.json"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        config = resp.json()

    _config_cache[country] = (config, now)
    logger.info("Fetched Tandem endpoint config", country=country)
    return config


async def _authenticate_tandem(
    db: AsyncSession,
    user_id: uuid.UUID,
    state: TandemUploadState,
) -> dict:
    """Get a valid Tandem access token for the user.

    Strategy:
    1. If cached token in upload_state is not expired, use it
    2. If expired but refresh_token exists, try refresh
    3. Otherwise, authenticate fresh using stored Tandem credentials
       via tconnectsync's TandemSourceApi (OIDC PKCE flow)

    Returns a dict with ``access_token``, ``pumper_id``, ``country``
    (ISO-3166 alpha-2, for per-country config fetch) and ``cloud`` (``"US"``
    or ``"EU"``, for tconnectsync auth routing).

    Raises ``TandemLegacyRegionError`` when the stored region value is a
    legacy bucket label (e.g. ``"EU"``) that cannot be resolved to a single
    country -- the user must re-select.

    Note: tconnectsync does not expose refresh tokens, so the refresh path
    (step 2) is currently unreachable. Kept for future compatibility.
    """
    now = datetime.now(UTC)

    cached_pumper_id = state.tandem_pumper_id or ""

    # Load credential and resolve country/cloud up front so all code paths
    # share the same routing decisions.
    cred_result = await db.execute(
        select(IntegrationCredential).where(
            IntegrationCredential.user_id == user_id,
            IntegrationCredential.integration_type == IntegrationType.TANDEM,
        )
    )
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise RuntimeError("Tandem integration not configured")

    country, cloud = resolve_country_or_raise(credential.region or "US")

    # 1. Check cached token
    if (
        state.tandem_access_token
        and state.tandem_token_expires_at
        and state.tandem_token_expires_at > now + timedelta(minutes=5)
    ):
        return {
            "access_token": decrypt_credential(state.tandem_access_token),
            "pumper_id": cached_pumper_id,
            "country": country,
            "cloud": cloud,
        }

    # 2. Try refresh token (currently unreachable -- see docstring)
    if state.tandem_refresh_token:
        try:
            token_data = await _refresh_tandem_token(
                decrypt_credential(state.tandem_refresh_token),
                cloud=cloud,
            )
            _cache_tokens(state, token_data)
            await db.commit()
            logger.info("Refreshed Tandem token", user_id=str(user_id))
            return {
                "access_token": token_data["access_token"],
                "pumper_id": cached_pumper_id,
                "country": country,
                "cloud": cloud,
            }
        except Exception:
            logger.warning(
                "Tandem token refresh failed, will re-authenticate",
                user_id=str(user_id),
            )

    # 3. Fresh authentication using stored credentials
    username = decrypt_credential(credential.encrypted_username)
    password = decrypt_credential(credential.encrypted_password)

    token_data = await _authenticate_fresh(username, password, cloud)
    _cache_tokens(state, token_data)

    pumper_id = token_data.get("pumper_id", "")
    if pumper_id:
        state.tandem_pumper_id = pumper_id

    await db.commit()
    logger.info(
        "Authenticated with Tandem via OIDC PKCE",
        user_id=str(user_id),
        country=country,
        cloud=cloud,
    )
    return {
        "access_token": token_data["access_token"],
        "pumper_id": pumper_id,
        "country": country,
        "cloud": cloud,
    }


async def _refresh_tandem_token(refresh_token: str, cloud: str = "US") -> dict:
    """Refresh the Tandem access token using the refresh_token grant.

    NOTE: Currently unreachable. tconnectsync does not expose refresh tokens,
    so _authenticate_fresh always returns refresh_token=None, and _cache_tokens
    never sets state.tandem_refresh_token. Kept for future use.
    """
    # Cloud-specific endpoints matching tconnectsync's TandemSourceApi.
    if cloud == "EU":
        token_endpoint = (
            "https://tdcservices.eu.tandemdiabetes.com/accounts/api/connect/token"
        )
        client_id = "1519e414-eeec-492e-8c5e-97bea4815a10"
    else:
        token_endpoint = (
            "https://tdcservices.tandemdiabetes.com/accounts/api/connect/token"
        )
        client_id = "0oa27ho9tpZE9Arjy4h7"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def _authenticate_fresh(username: str, password: str, cloud: str) -> dict:
    """Authenticate with Tandem using stored credentials.

    Uses tconnectsync's TandemSourceApi which handles the OIDC PKCE flow
    (login + authorization code exchange via tdcservices.tandemdiabetes.com).
    ``cloud`` must be ``"US"`` or ``"EU"`` -- the only two values tconnectsync
    accepts (derived from the user's country via ``country_to_cloud``).

    Extracts accessToken (camelCase), accessTokenExpiresAt, and pumperId
    from the API instance after successful login.
    """
    import asyncio

    from tconnectsync.api.tandemsource import TandemSourceApi

    def _login():
        api = TandemSourceApi(email=username, password=password, region=cloud)

        # tconnectsync stores the token as self.accessToken (camelCase).
        # See: tconnectsync/api/tandemsource.py line 204
        access_token = getattr(api, "accessToken", None)
        if not access_token:
            raise RuntimeError(
                "Could not extract Tandem access token from TandemSourceApi. "
                "Expected attribute 'accessToken' not found."
            )

        # Compute real expires_in from accessTokenExpiresAt (arrow datetime)
        expires_in = 3600
        token_expiry = getattr(api, "accessTokenExpiresAt", None)
        if token_expiry is not None:
            try:
                import arrow as arrow_lib

                diff = (arrow_lib.get(token_expiry) - arrow_lib.get()).total_seconds()
                if diff > 0:
                    expires_in = int(diff)
            except Exception:
                logger.warning(
                    "Failed to parse accessTokenExpiresAt, using default 3600s"
                )

        # Extract pumperId for deviceAssignmentId in upload payloads
        pumper_id = getattr(api, "pumperId", None) or ""

        return {
            "access_token": access_token,
            "expires_in": expires_in,
            "refresh_token": None,  # tconnectsync does not expose refresh tokens
            "pumper_id": str(pumper_id),
        }

    return await asyncio.to_thread(_login)


def _cache_tokens(state: TandemUploadState, token_data: dict) -> None:
    """Cache the OAuth tokens in the upload state (encrypted)."""
    state.tandem_access_token = encrypt_credential(token_data["access_token"])
    expires_in = token_data.get("expires_in", 3600)
    state.tandem_token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

    refresh_token = token_data.get("refresh_token")
    if refresh_token:
        state.tandem_refresh_token = encrypt_credential(refresh_token)


async def get_last_event_uploaded(
    access_token: str,
    config: dict,
    serial_number: int,
    model_number: int,
) -> int:
    """Query Tandem's getLastEventUploaded endpoint for incremental sync.

    Returns the maxPumpEventIndex (events with index > this should be uploaded).
    """
    url = config.get("getLastEventUploadedUrl")
    if not url:
        logger.warning("No getLastEventUploadedUrl in config, starting from 0")
        return 0

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            url,
            params={
                "serialNumber": str(serial_number),
                "modelNumber": str(model_number),
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code == 404:
            return 0
        resp.raise_for_status()
        data = resp.json()
        return data.get("maxPumpEventIndex", 0)


def build_upload_payload(
    pump_info: PumpHardwareInfo,
    raw_events: list[PumpRawEvent],
    settings_b64: str | None = None,
    device_assignment_id: str = "",
) -> dict:
    """Build the Tandem upload payload JSON matching the official app schema.

    Schema: UploadPayload > Package > Device > Data (misc, settings, events)
    """
    # Build misc object
    misc = {
        "platform": "GlycemicGPT Mobile [Android]",
        "pumpFeatures": pump_info.pump_features or {},
        "pumpAPIVersion": "",
        "appVersion": "2.9.1 (3368rb)",
        "uploaderClient": "mobile_tconnect",
        "pumpDateTime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "clientDateTimeWithOffset": datetime.now(UTC).strftime(
            "%Y-%m-%dT%H:%M:%S+00:00"
        ),
        "deviceAssignmentId": device_assignment_id,
    }

    # Build events list (each is the raw base64 bytes from the pump)
    events_list = [ev.raw_bytes_b64 for ev in raw_events] if raw_events else None

    # Build data object
    data = {"misc": misc}
    if settings_b64:
        data["settings"] = settings_b64
    if events_list:
        data["events"] = events_list

    # Build device object
    device = {
        "modelNum": pump_info.model_number,
        "serialNum": pump_info.serial_number,
        "partNum": pump_info.part_number,
        "pumpRev": pump_info.pump_rev,
        "armSwVer": pump_info.arm_sw_ver,
        "mspSwVer": pump_info.msp_sw_ver,
        "configABits": pump_info.config_a_bits,
        "configBBits": pump_info.config_b_bits,
        "pcbaSN": pump_info.pcba_sn,
        "pcbaRev": pump_info.pcba_rev,
        "data": data,
    }

    return {
        "client": "mHealth",
        "package": {"device": device},
    }


async def _post_upload(
    access_token: str,
    config: dict,
    payload: dict,
) -> dict:
    """POST the upload payload to Tandem's cloud with HMAC-SHA1 signing."""
    url = config.get("postUploadUrl")
    if not url:
        raise RuntimeError("No postUploadUrl in Tandem endpoint config")

    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    tdc_signature = sign_tdc_token(json_bytes)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "TDCToken": f"token {tdc_signature}",
    }

    async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, content=json_bytes, headers=headers)
        resp.raise_for_status()
        body = resp.json() if resp.content else {}
        # A 200 from Tandem can still report per-event errors in the body.
        # Treat any populated `errors` array as a failure so we don't mark
        # those events as uploaded -- otherwise we'd silently drop them on
        # the floor, exactly the kind of silent-success bug the bundled fix
        # is meant to eliminate.
        if isinstance(body, dict) and body.get("errors"):
            raise RuntimeError(
                f"Tandem cloud accepted the request but reported "
                f"{len(body['errors'])} per-event error(s)."
            )
        return body


async def upload_to_tandem(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Main upload orchestrator.

    1. Get/create upload state
    2. Authenticate with Tandem
    3. Get pump hardware info
    4. Query getLastEventUploaded for incremental sync
    5. Fetch un-uploaded raw events from DB
    6. Build upload payload
    7. Sign and POST to Tandem cloud
    8. Mark events as uploaded, update state
    """
    now = datetime.now(UTC)

    # Get-or-create the upload state, then row-lock it for the duration of
    # this upload. The helper does an INSERT ... ON CONFLICT DO NOTHING
    # first so a concurrent first-run upload + reset don't both observe
    # "no row" and race each other into a uniqueness collision.
    state = await _lock_or_create_upload_state(db, user_id)

    # Get pump hardware info
    hw_result = await db.execute(
        select(PumpHardwareInfo).where(PumpHardwareInfo.user_id == user_id)
    )
    pump_info = hw_result.scalar_one_or_none()
    if not pump_info:
        msg = "No pump hardware info available. Pair your pump first."
        state.last_upload_status = "error"
        state.last_error = msg
        await db.commit()
        return {"message": msg, "events_uploaded": 0, "status": "error"}

    # Authenticate
    try:
        auth_result = await _authenticate_tandem(db, user_id, state)
    except TandemLegacyRegionError as e:
        # Mark state then re-raise so the caller (HTTP trigger or scheduler)
        # can decide how to surface the legacy-region prompt.
        state.last_upload_status = "needs_country"
        state.last_error = str(e)
        await db.commit()
        logger.warning(
            "Tandem upload blocked: legacy region requires re-select",
            user_id=str(user_id),
        )
        raise
    except Exception as e:
        # Don't persist the raw exception string to last_error -- tconnectsync
        # / httpx exceptions can include URLs with query strings, response
        # bodies, or auth headers. Keep the detail in the structured log and
        # surface a stable user-facing message.
        public_msg = "Tandem authentication failed. Please re-connect your account."
        state.last_upload_status = "error"
        state.last_error = public_msg
        await db.commit()
        logger.error("Tandem upload auth failed", user_id=str(user_id), error=str(e))
        return {"message": public_msg, "events_uploaded": 0, "status": "error"}

    access_token = auth_result["access_token"]
    pumper_id = auth_result.get("pumper_id", "")
    country = auth_result["country"]

    # Fetch per-country endpoint config
    try:
        config = await fetch_tandem_config(country)
    except Exception as e:
        public_msg = "Failed to fetch Tandem endpoint config. Please try again."
        state.last_upload_status = "error"
        state.last_error = public_msg
        await db.commit()
        logger.error(
            "Tandem config fetch failed",
            user_id=str(user_id),
            country=country,
            error=str(e),
        )
        return {"message": public_msg, "events_uploaded": 0, "status": "error"}

    # Diagnostic only: query the cloud's max event index for logging. Do NOT
    # use it to filter the upload set. The original implementation filtered
    # `sequence_number > max(cloud_max, local_max)`, which silently dropped
    # every event whenever the user also ran the official t:connect app
    # (which had pushed events with much higher sequence numbers).
    # Tandem's cloud is idempotent on (modelNumber, serialNumber,
    # sequenceNumber), so re-sending a known event is a safe no-op.
    try:
        cloud_max_index = await get_last_event_uploaded(
            access_token, config, pump_info.serial_number, pump_info.model_number
        )
        if cloud_max_index > state.max_event_index_uploaded:
            logger.info(
                "Tandem cloud reports a higher event index than our local "
                "high-water mark; this is normal when another client (e.g. the "
                "official t:connect app) is also uploading.",
                user_id=str(user_id),
                cloud_max=cloud_max_index,
                local_max=state.max_event_index_uploaded,
            )
    except Exception as e:
        logger.warning(
            "getLastEventUploaded failed; continuing with upload anyway",
            user_id=str(user_id),
            error=str(e),
        )

    # Fetch un-uploaded raw events. The `uploaded_to_tandem` flag is the
    # single source of truth for what still needs to be sent.
    events_result = await db.execute(
        select(PumpRawEvent)
        .where(
            PumpRawEvent.user_id == user_id,
            PumpRawEvent.uploaded_to_tandem.is_(False),
        )
        .order_by(PumpRawEvent.sequence_number.asc())
        .limit(_MAX_EVENTS_PER_UPLOAD)
    )
    raw_events = list(events_result.scalars().all())

    if not raw_events:
        state.last_upload_at = now
        state.last_upload_status = "success"
        state.last_error = None
        await db.commit()
        return {
            "message": "No pending events to upload",
            "events_uploaded": 0,
            "status": "success",
        }

    # Build and upload payload
    payload = build_upload_payload(
        pump_info, raw_events, device_assignment_id=pumper_id
    )

    try:
        await _post_upload(access_token, config, payload)
    except httpx.HTTPStatusError as e:
        public_msg = f"Tandem cloud rejected the upload (HTTP {e.response.status_code})."
        state.last_upload_status = "error"
        state.last_error = public_msg
        await db.commit()
        logger.error(
            "Tandem upload failed",
            user_id=str(user_id),
            status=e.response.status_code,
        )
        return {"message": public_msg, "events_uploaded": 0, "status": "error"}
    except Exception as e:
        public_msg = "Tandem upload failed. Please try again."
        state.last_upload_status = "error"
        state.last_error = public_msg
        await db.commit()
        logger.error("Tandem upload failed", user_id=str(user_id), error=str(e))
        return {"message": public_msg, "events_uploaded": 0, "status": "error"}

    # Mark events as uploaded
    event_ids = [ev.id for ev in raw_events]
    max_seq = max(ev.sequence_number for ev in raw_events)

    await db.execute(
        update(PumpRawEvent)
        .where(PumpRawEvent.id.in_(event_ids))
        .values(uploaded_to_tandem=True, uploaded_at=now)
    )

    # Update state
    state.last_upload_at = now
    state.last_upload_status = "success"
    state.last_error = None
    state.max_event_index_uploaded = max(state.max_event_index_uploaded, max_seq)
    await db.commit()

    logger.info(
        "Tandem upload complete",
        user_id=str(user_id),
        events_uploaded=len(raw_events),
        max_sequence=max_seq,
    )

    return {
        "message": f"Uploaded {len(raw_events)} events to Tandem cloud",
        "events_uploaded": len(raw_events),
        "status": "success",
    }


async def reset_tandem_upload_state(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Reset the upload high-water mark and re-queue every stored raw event.

    Used to recover from situations where the local state has drifted out
    of sync with what's actually uploadable -- e.g. after a pump re-pair,
    after a sequence-counter reset, or when migrating off the legacy
    incremental-sync logic that silently filtered out queued events.

    Materializes the upload state row if missing, then takes a row-lock so
    a concurrent ``upload_to_tandem`` cannot re-flag the same rows as
    ``uploaded_to_tandem=True`` immediately after we clear them.
    Idempotent: safe to call repeatedly.
    """
    state = await _lock_or_create_upload_state(db, user_id)
    state.max_event_index_uploaded = 0
    state.last_error = None
    state.last_upload_status = None

    update_result = await db.execute(
        update(PumpRawEvent)
        .where(PumpRawEvent.user_id == user_id)
        .values(uploaded_to_tandem=False, uploaded_at=None)
    )
    requeued = update_result.rowcount or 0

    await db.commit()

    logger.info(
        "Tandem upload state reset",
        user_id=str(user_id),
        events_requeued=requeued,
    )

    return {
        "message": f"Upload state reset; {requeued} events re-queued for upload.",
        "events_requeued": requeued,
    }
