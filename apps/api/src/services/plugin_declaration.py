"""Plugin declaration service.

Manages per-user active pump plugin declarations with upsert semantics.
"""

import uuid

import sqlalchemy as sa
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_config import get_logger
from src.models.plugin_declaration import PluginDeclaration
from src.schemas.plugin_declaration import PluginDeclarationCreate

logger = get_logger(__name__)


async def upsert_declaration(
    user_id: uuid.UUID,
    data: PluginDeclarationCreate,
    db: AsyncSession,
) -> PluginDeclaration:
    """Insert or fully replace the user's plugin declaration.

    Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE for atomic upsert.
    """
    stmt = (
        pg_insert(PluginDeclaration)
        .values(
            user_id=user_id,
            plugin_id=data.plugin_id,
            plugin_name=data.plugin_name,
            plugin_version=data.plugin_version,
            declared_categories=data.declared_categories,
            category_mappings=data.category_mappings,
        )
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "plugin_id": data.plugin_id,
                "plugin_name": data.plugin_name,
                "plugin_version": data.plugin_version,
                "declared_categories": data.declared_categories,
                "category_mappings": data.category_mappings,
                "updated_at": sa.func.now(),
            },
        )
        .returning(PluginDeclaration)
    )
    result = await db.execute(stmt)
    declaration = result.scalar_one()
    await db.commit()
    await db.refresh(declaration)

    logger.debug(
        "Upserted plugin declaration",
        plugin_id=data.plugin_id,
    )

    return declaration


async def get_declaration(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> PluginDeclaration | None:
    """Get the user's plugin declaration, or None if not set."""
    result = await db.execute(
        select(PluginDeclaration).where(PluginDeclaration.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def delete_declaration(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """Delete the user's plugin declaration. Returns True if a row was deleted."""
    result = await db.execute(
        delete(PluginDeclaration).where(PluginDeclaration.user_id == user_id)
    )
    await db.commit()
    deleted = result.rowcount > 0

    if deleted:
        logger.debug("Deleted plugin declaration")

    return deleted
