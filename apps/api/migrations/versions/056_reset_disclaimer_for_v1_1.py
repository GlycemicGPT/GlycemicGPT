"""Reset disclaimer_acknowledged for all users (disclaimer v1.1).

Disclaimer v1.1 adds a substantive new acknowledgment about AI data
processing -- specifically, that configuring a cloud-hosted AI provider
transmits health data to that provider, while local AI providers keep
data on the user's own network. Existing users acknowledged the v1.0
disclaimer, which had no such language. Their prior consent does not
cover the v1.1 wording, so they must re-acknowledge.

This migration sets `users.disclaimer_acknowledged = False` for every
existing row. On next dashboard load, the AuthDisclaimerGate sees the
flag is false and shows the v1.1 modal. After they accept,
`/api/disclaimer/acknowledge-auth` sets the flag back to true.

The session-based pre-auth modal handles re-prompting via a separate
mechanism: `/api/disclaimer/status` now treats stored acknowledgments
with an outdated `disclaimer_version` as not-acknowledged. The User
model has no version column to compare against, so we use this
one-shot reset instead.

Downgrade is a no-op: there is no safe way to know which users had
acknowledged before the reset.

Revision ID: 056_reset_disclaimer_for_v1_1
Revises: 055_forecast_snapshots
Create Date: 2026-05-14
"""

from alembic import op

revision = "056_reset_disclaimer_for_v1_1"
down_revision = "055_forecast_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent by construction: re-running this migration on a database
    # where every user already has disclaimer_acknowledged=False is a no-op
    # (the WHERE clause matches zero rows). However, do NOT copy this
    # migration verbatim for future disclaimer version bumps -- create a
    # new migration with a fresh revision id. Reusing this one would
    # blindly re-prompt users who already acknowledged the newer version
    # in the gap between deploys, which is a worse UX than leaving them
    # alone. For a future bump (e.g. v1.2), prefer adding a version
    # column to the users table so the re-prompt can be scoped to users
    # whose stored acknowledgment is for an outdated version, mirroring
    # the session-based flow.
    op.execute(
        "UPDATE users SET disclaimer_acknowledged = FALSE "
        "WHERE disclaimer_acknowledged = TRUE"
    )


def downgrade() -> None:
    # Intentional no-op: there is no safe way to know which users had
    # acknowledged before the reset, so downgrading cannot restore their
    # prior state.
    pass
