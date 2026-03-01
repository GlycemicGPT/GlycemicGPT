"""API key scopes for third-party access control.

Phase 1 is read-heavy with limited write access (device management only).
"""

VALID_SCOPES: frozenset[str] = frozenset(
    {
        "read:glucose",  # Read glucose readings
        "read:pump",  # Read pump events/status
        "read:alerts",  # Read alerts
        "read:profile",  # Read user profile
        "write:device",  # Register/manage devices
    }
)
