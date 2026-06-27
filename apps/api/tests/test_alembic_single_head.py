"""Guard: the Alembic migration graph must have exactly one head.

A second head means two migrations declare the same ``down_revision`` (a merge
was missed). That ambiguity has repeatedly bitten us here -- ``alembic upgrade
head`` errors out and ``current`` / ``heads`` disagree. This test fails the
moment a real second head appears, inside the existing Backend Tests gate (no
DB and no new CI job required).
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

# tests/ -> apps/api. Resolve from the file so the check is independent of the
# process working directory (alembic.ini's ``script_location`` is otherwise
# resolved relative to cwd).
_API_ROOT = Path(__file__).resolve().parents[1]


def test_single_alembic_head() -> None:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "migrations"))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1, f"expected exactly one Alembic head, found {heads}"
