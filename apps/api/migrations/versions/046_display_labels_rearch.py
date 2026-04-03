"""Rearchitect bolus display labels as first-class entities.

Replaces the category_labels dict and custom_categories list with a
display_labels JSONB array of DisplayLabel objects. Each label has an
id, user-visible text, optional computation_role, optional pump_source,
and sort_order.

Revision ID: 046_display_labels_rearch
Revises: 045_add_custom_categories
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "046_display_labels_rearch"
down_revision = "045_add_custom_categories"
branch_labels = None
depends_on = None

# Computation roles (the 6 built-in roles, AI_SUGGESTED removed)
COMPUTATION_ROLES = {
    "AUTO_CORRECTION",
    "FOOD",
    "FOOD_AND_CORRECTION",
    "CORRECTION",
    "OVERRIDE",
    "OTHER",
}

DEFAULT_DISPLAY_LABELS = [
    {
        "id": "auto_corr",
        "label": "Auto Corr",
        "computation_role": "AUTO_CORRECTION",
        "pump_source": None,
        "sort_order": 0,
    },
    {
        "id": "meal",
        "label": "Meal",
        "computation_role": "FOOD",
        "pump_source": None,
        "sort_order": 1,
    },
    {
        "id": "meal_corr",
        "label": "Meal+Corr",
        "computation_role": "FOOD_AND_CORRECTION",
        "pump_source": None,
        "sort_order": 2,
    },
    {
        "id": "correction",
        "label": "Correction",
        "computation_role": "CORRECTION",
        "pump_source": None,
        "sort_order": 3,
    },
    {
        "id": "override",
        "label": "Override",
        "computation_role": "OVERRIDE",
        "pump_source": None,
        "sort_order": 4,
    },
    {
        "id": "other",
        "label": "Other",
        "computation_role": "OTHER",
        "pump_source": None,
        "sort_order": 5,
    },
]

# Slug mapping for old category keys -> stable ids
_KEY_TO_ID = {
    "AUTO_CORRECTION": "auto_corr",
    "FOOD": "meal",
    "FOOD_AND_CORRECTION": "meal_corr",
    "CORRECTION": "correction",
    "OVERRIDE": "override",
    "AI_SUGGESTED": "ai_suggested",
    "OTHER": "other",
}


def _migrate_category_labels(old_labels: dict) -> list[dict]:
    """Convert old {key: label_text} dict to DisplayLabel array."""
    result = []
    seen_roles = set()
    sort_order = 0

    # Process existing labels in a stable order
    ordered_keys = [
        "AUTO_CORRECTION",
        "FOOD",
        "FOOD_AND_CORRECTION",
        "CORRECTION",
        "OVERRIDE",
        "AI_SUGGESTED",
        "OTHER",
    ]

    for key in ordered_keys:
        if key not in old_labels:
            continue
        label_text = old_labels[key]
        label_id = _KEY_TO_ID.get(key, key.lower())

        entry = {
            "id": label_id,
            "label": label_text,
            "computation_role": key if key in COMPUTATION_ROLES else None,
            "pump_source": None,
            "sort_order": sort_order,
        }

        if key in COMPUTATION_ROLES:
            seen_roles.add(key)

        result.append(entry)
        sort_order += 1

    # Add any missing default roles
    for default in DEFAULT_DISPLAY_LABELS:
        role = default["computation_role"]
        if role and role not in seen_roles:
            entry = dict(default)
            entry["sort_order"] = sort_order
            result.append(entry)
            sort_order += 1

    return result


def upgrade() -> None:
    # 1. Add display_labels column
    op.add_column(
        "analytics_configs",
        sa.Column(
            "display_labels",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
    )

    # 2. Migrate existing data
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, category_labels FROM analytics_configs WHERE category_labels IS NOT NULL")
    )
    for row in rows:
        row_id = row[0]
        old_labels = row[1]
        if isinstance(old_labels, str):
            old_labels = json.loads(old_labels)
        if old_labels:
            new_labels = _migrate_category_labels(old_labels)
            conn.execute(
                sa.text("UPDATE analytics_configs SET display_labels = :labels WHERE id = :id"),
                {"labels": json.dumps(new_labels), "id": row_id},
            )

    # 3. Drop old columns
    # Note: custom_categories was a schema-ready placeholder (045) that was
    # never populated by any service or UI -- safe to drop without migration.
    op.drop_column("analytics_configs", "category_labels")
    op.drop_column("analytics_configs", "custom_categories")


def downgrade() -> None:
    # Re-add old columns
    op.add_column(
        "analytics_configs",
        sa.Column(
            "category_labels",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
    )
    op.add_column(
        "analytics_configs",
        sa.Column(
            "custom_categories",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
    )

    # Reverse-migrate display_labels -> category_labels
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, display_labels FROM analytics_configs WHERE display_labels IS NOT NULL")
    )
    for row in rows:
        row_id = row[0]
        labels = row[1]
        if isinstance(labels, str):
            labels = json.loads(labels)
        if labels:
            old_dict = {}
            for item in labels:
                role = item.get("computation_role")
                if role:
                    old_dict[role] = item["label"]
            conn.execute(
                sa.text("UPDATE analytics_configs SET category_labels = :labels WHERE id = :id"),
                {"labels": json.dumps(old_dict), "id": row_id},
            )

    op.drop_column("analytics_configs", "display_labels")
