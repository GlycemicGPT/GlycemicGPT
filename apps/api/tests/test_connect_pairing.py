"""Unit tests for the Medtronic Connect pairing-token helper."""

import json
import time
import uuid

import pytest

from src.core.encryption import encrypt_credential
from src.services.integrations.medtronic import connect_pairing as cp
from src.services.integrations.medtronic.connect_pairing import (
    PairingTokenError,
    decode_pairing_token,
    issue_pairing_token,
    pairing_token_jti,
)


def test_issue_then_decode_roundtrips_user_id():
    uid = uuid.uuid4()
    token, expires_at = issue_pairing_token(uid)
    assert decode_pairing_token(token) == uid
    assert expires_at.tzinfo is not None


def test_garbage_token_rejected():
    with pytest.raises(PairingTokenError, match="Invalid pairing token"):
        decode_pairing_token("not-a-fernet-blob")


def test_pairing_token_jti_present_and_unique():
    t1, _ = issue_pairing_token(uuid.uuid4())
    t2, _ = issue_pairing_token(uuid.uuid4())
    j1, j2 = pairing_token_jti(t1), pairing_token_jti(t2)
    assert j1 and j2 and j1 != j2


def test_pairing_token_jti_rejects_garbage():
    with pytest.raises(PairingTokenError):
        pairing_token_jti("not-a-fernet-blob")


def test_wrong_purpose_rejected():
    # A different Fernet blob (e.g. a pkce_session shape) must not authenticate.
    blob = encrypt_credential(json.dumps({"v": "x", "r": "US", "u": "uid"}))
    with pytest.raises(PairingTokenError, match="Not a pairing token"):
        decode_pairing_token(blob)


def test_expired_token_rejected(monkeypatch):
    uid = uuid.uuid4()
    token, _ = issue_pairing_token(uid)
    # Jump past the TTL. Capture the value first so the patched time.time()
    # (cp.time IS the time module) doesn't recurse into itself.
    future = time.time() + cp.PAIR_TOKEN_TTL_SECONDS + 5
    monkeypatch.setattr(cp.time, "time", lambda: future)
    with pytest.raises(PairingTokenError, match="expired"):
        decode_pairing_token(token)


def test_malformed_uid_rejected():
    blob = encrypt_credential(
        json.dumps(
            {"uid": "not-a-uuid", "p": "medtronic_connect_pair", "ts": int(time.time())}
        )
    )
    with pytest.raises(PairingTokenError, match="Malformed"):
        decode_pairing_token(blob)
