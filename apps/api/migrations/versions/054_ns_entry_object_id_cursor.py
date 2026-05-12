"""Add `last_entry_object_id` to nightscout_connections.

Switches the entries cursor from `dateString` (recorded time) to NS's
MongoDB `_id` (insertion time, monotonically increasing). The old
cursor missed entries that uploaders backfilled into NS *after* our
last sync but with `dateString` values from *before* our last sync
window. The Dexcom Share -> Nightscout bridge is the most common
example: a brief disconnect causes the bridge to upload missed
readings later with their original timestamps, which our cursor had
already advanced past.

Mongo `_id` is monotonic by insertion time regardless of `dateString`,
so a backfilled entry inserted at T+5min always gets a larger `_id`
than entries inserted at T. Querying `find[_id][$gt]=<lastSeen>` is
immune to late uploads with old timestamps.

NULL on existing rows means "no `_id` cursor yet" -- the sync code
falls back to the legacy `last_synced_at` (dateString-based) cursor
for the next sync, then locks in the new ObjectId cursor afterward.
No backfill migration is required; the transition is a single sync
cycle per connection.

Treatments and devicestatus already use server-side `created_at` and
are immune to this class of bug. They are intentionally unchanged.

Closes issue #598.

Revision ID: 054_ns_entry_object_id_cursor
Revises: 053_ai_max_response_tokens
Create Date: 2026-05-12
"""

import sqlalchemy as sa
from alembic import op

revision = "054_ns_entry_object_id_cursor"
down_revision = "053_ai_max_response_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nightscout_connections",
        sa.Column("last_entry_object_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nightscout_connections", "last_entry_object_id")
