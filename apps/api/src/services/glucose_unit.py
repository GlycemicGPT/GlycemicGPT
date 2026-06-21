"""Resolve a user's preferred glucose display unit.

Backend text-rendering paths -- predictive alerts, escalations, Telegram
notifications and command replies -- often hold only a ``user_id`` but must
render glucose in the *data owner's* unit (the patient's, never a caregiver's
or an emergency contact's). This is the single helper they share so the lookup
and the mg/dL fallback live in one place.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.units import GlucoseUnit
from src.models.user import User


async def resolve_glucose_unit(db: AsyncSession, user_id: uuid.UUID) -> GlucoseUnit:
    """Return the user's configured glucose display unit, defaulting to mg/dL.

    Reads only the ``glucose_unit`` column (no full ``User`` load). Falls back
    to mg/dL if the user can't be found, matching the column's non-null
    ``server_default`` so a missing row can never surface mmol unexpectedly.
    """
    result = await db.execute(select(User.glucose_unit).where(User.id == user_id))
    return result.scalar_one_or_none() or GlucoseUnit.MGDL
