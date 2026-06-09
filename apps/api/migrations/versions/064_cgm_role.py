"""Cross-source CGM primary/secondary role (Story 43.10).

Adds ``cgm_role`` (``primary`` / ``secondary`` / ``off``) to both
CGM-providing source tables -- ``nightscout_connections`` and
``integration_credentials`` (Dexcom). When a user has more than one CGM
source feeding ``glucose_readings`` (e.g. Dexcom Share AND a Loop-via-
Nightscout connection reading the same sensor), the glucose read
endpoints drive charts/stats from the ``primary`` source only and treat
``secondary`` / ``off`` rows as audit-only, so AGP / TIR / CGM summary
aren't double-counted.

Existing rows default to ``primary`` (``server_default``) so nothing is
hidden until the user explicitly picks a primary -- a single-source user
is unaffected, and a multi-source user opts into dedupe via the picker.
New sources are assigned a role at creation time (primary if the user
has no existing primary, else secondary).

Revision ID: 064_cgm_role
Revises: 063_pump_event_dedupe_hash
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "064_cgm_role"
down_revision: str | None = "063_pump_event_dedupe_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_CHECK = "cgm_role IN ('primary', 'secondary', 'off')"


def upgrade() -> None:
    for table in ("nightscout_connections", "integration_credentials"):
        op.add_column(
            table,
            sa.Column(
                "cgm_role",
                sa.String(length=16),
                nullable=False,
                server_default="primary",
            ),
        )
        op.create_check_constraint(
            f"ck_{table}_cgm_role",
            table,
            _ROLE_CHECK,
        )


def downgrade() -> None:
    for table in ("nightscout_connections", "integration_credentials"):
        op.drop_constraint(f"ck_{table}_cgm_role", table, type_="check")
        op.drop_column(table, "cgm_role")
