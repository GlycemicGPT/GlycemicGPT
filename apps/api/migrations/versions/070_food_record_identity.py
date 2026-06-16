"""Add food-identity confirmation columns to food_records (Story 50.H2).

Food *misidentification* is the dominant, upstream error in LLM carb vision, and
grounding (50.E1/E2) amplifies it: grounding a misidentified food to USDA /
restaurant data certifies a confident-wrong answer with an authoritative
citation. So identity becomes a confirmable thing the user owns, separate from
the carb correction (50.C1), and external authoritative grounding only applies
to a confirmed-or-corrected identity.

Two columns, mirroring the preserve-the-original pattern used for carbs
(``food_description`` keeps the AI-identified name, like ``carbs_low/high`` keep
the AI estimate):

* ``confirmed_food_name`` -- the user's confirmed-or-corrected identity. NULL
  until the user acts. This is the identity used as the grounding key (and the
  one 50.H3 records as "the identity grounding ran against").
* ``identity_confirmed`` -- whether the identity has been confirmed. Gates
  external grounding: while False the estimate stays vision-only.

Attribution only -- nothing here is read by IoB / treatment_safety / carb-ratio
math.

Revision ID: 070_food_record_identity
Revises: 069_food_record_grounding
Create Date: 2026-06-16
"""

import sqlalchemy as sa
from alembic import op

revision = "070_food_record_identity"
down_revision = "069_food_record_grounding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The user-confirmed / corrected food identity. NULL = not yet confirmed.
    op.add_column(
        "food_records",
        sa.Column("confirmed_food_name", sa.Text(), nullable=True),
    )
    # Whether the identity has been confirmed. NOT NULL with a False server
    # default so every existing row is correctly "unconfirmed" (and therefore
    # ungrounded-by-external-sources) without a data backfill.
    op.add_column(
        "food_records",
        sa.Column(
            "identity_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("food_records", "identity_confirmed")
    op.drop_column("food_records", "confirmed_food_name")
