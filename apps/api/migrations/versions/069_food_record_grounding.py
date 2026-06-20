"""Add grounding-attribution columns to food_records (Story 50.E1).

Grounding sharpens the *descriptive* carb estimate by reconciling it against the
user's own logged history (RAG, USER_PROVIDED) and published nutrition facts
(USDA FoodData Central / Open Food Facts, RESEARCHED/AUTHORITATIVE). These three
nullable columns record *which* source grounded a given estimate so the API can
cite provenance. They are attribution only -- the carb values themselves stay in
``carbs_low`` / ``carbs_high`` (the immutable vision estimate) and ``corrected_*``
(the user's truth); nothing here couples a record into IoB / treatment_safety /
carb-ratio math.

This is the deferred 50.B amendment (Open Food Facts requires attribution, so a
provenance column was always going to be needed once grounding landed).

Revision ID: 069_food_record_grounding
Revises: 068_basal_injection_event_type
Create Date: 2026-06-15
"""

import sqlalchemy as sa
from alembic import op

revision = "069_food_record_grounding"
down_revision = "068_basal_injection_event_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Human-readable source name shown in the citation (e.g. "USDA FoodData
    # Central", "Open Food Facts", "Your meal history").
    op.add_column(
        "food_records",
        sa.Column("grounding_source", sa.String(length=120), nullable=True),
    )
    # Citation link (USDA food page / OFF product page). NULL for own-history.
    op.add_column(
        "food_records",
        sa.Column("grounding_source_url", sa.Text(), nullable=True),
    )
    # Trust-tier marker for the grounding source, mirroring the knowledge_chunks
    # tiers: USER_PROVIDED (own history) / RESEARCHED / AUTHORITATIVE (published).
    # A plain string (not a DB enum) matches knowledge_chunks.trust_tier.
    op.add_column(
        "food_records",
        sa.Column("grounding_trust_tier", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("food_records", "grounding_trust_tier")
    op.drop_column("food_records", "grounding_source_url")
    op.drop_column("food_records", "grounding_source")
