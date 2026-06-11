"""Short-lived pairing token for the Medtronic Connect local login-helper CLI.

The CarePartner initial login can't happen on the backend (the only allowed
interactive grant redirects to a mobile-app custom scheme; see
``_bmad-output/medtronic-connect-findings.md``). So a one-time **local CLI**
drives the browser login + captures the auth code. To let that CLI talk to the
user's GlycemicGPT backend WITHOUT the user's password/session, the web UI mints
a short-lived **pairing token** that the CLI presents in the
``X-Connect-Pair-Token`` header.

The token only authorizes the two Connect handshake calls (``/authorize-url`` +
``/exchange``) for exactly one user. It is Fernet-encrypted, user-bound, and
expires quickly. It is intentionally **not** a session: it can't be used for any
other endpoint, and the refresh token is exchanged + stored server-side, so it
never reaches the CLI.

Single-use: each token carries a random ``jti``. The credential-creating step
(``/exchange``) consumes that jti once via Redis (``consume_token_once``), so a
token that has already completed a connection is inert -- this prevents a leaked
token (e.g. a user pasting the helper command somewhere public) from later being
replayed to attach a different CareLink account. ``/authorize-url`` does not
consume the token (it only returns an authorize URL and is harmless to repeat).
The token itself is stateless (Fernet) apart from that one consumed marker.
Single-use is enforced via Redis and **fails closed**: ``consume_token_once``
raises if Redis is unavailable and the exchange returns a retryable 503
(the token is not consumed, so the same helper command works once Redis is
back) rather than degrading replay protection to the short TTL + user
binding alone.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime, timedelta

from src.core.encryption import decrypt_credential, encrypt_credential

#: Header the CLI uses to present the pairing token.
CONNECT_PAIR_TOKEN_HEADER = "X-Connect-Pair-Token"

#: Distinguishes a pairing token from any other Fernet blob (e.g. pkce_session).
_PURPOSE = "medtronic_connect_pair"

#: Pairing tokens are short-lived -- long enough to run the CLI + solve the
#: captcha, short enough to limit exposure of a leaked token.
PAIR_TOKEN_TTL_SECONDS = 900  # 15 minutes


class PairingTokenError(Exception):
    """The pairing token is missing, malformed, wrong-purpose, or expired."""


def issue_pairing_token(user_id: uuid.UUID) -> tuple[str, datetime]:
    """Mint a pairing token for ``user_id``. Returns ``(token, expires_at)``."""
    now = int(time.time())
    token = encrypt_credential(
        json.dumps(
            {"uid": str(user_id), "p": _PURPOSE, "ts": now, "jti": uuid.uuid4().hex}
        )
    )
    expires_at = datetime.fromtimestamp(now, tz=UTC) + timedelta(
        seconds=PAIR_TOKEN_TTL_SECONDS
    )
    return token, expires_at


def _decode(token: str) -> dict:
    try:
        data = json.loads(decrypt_credential(token))
    except Exception as e:  # noqa: BLE001 - any decrypt/parse failure is invalid
        raise PairingTokenError("Invalid pairing token") from e
    if not isinstance(data, dict) or data.get("p") != _PURPOSE:
        raise PairingTokenError("Not a pairing token")
    if int(time.time()) - int(data.get("ts", 0)) > PAIR_TOKEN_TTL_SECONDS:
        raise PairingTokenError("Pairing token expired")
    return data


def decode_pairing_token(token: str) -> uuid.UUID:
    """Validate a pairing token and return its user id. Raises PairingTokenError."""
    data = _decode(token)
    try:
        return uuid.UUID(str(data["uid"]))
    except (KeyError, ValueError) as e:
        raise PairingTokenError("Malformed pairing token") from e


def pairing_token_jti(token: str) -> str:
    """Validate a pairing token and return its single-use id. Raises PairingTokenError."""
    data = _decode(token)
    jti = data.get("jti")
    if not jti or not isinstance(jti, str):
        raise PairingTokenError("Pairing token missing jti")
    return jti
