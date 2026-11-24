"""partial unique import draft source_ref

Revision ID: 7062d8fe6543
Revises: 0a7bb29f33d4
Create Date: 2026-11-24 22:47:28.921361

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7062d8fe6543"
down_revision: Union[str, Sequence[str], None] = "0a7bb29f33d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    """Replace global UNIQUE(source_ref) with a partial unique index on active drafts."""
    with op.batch_alter_table(
        "import_drafts", schema=None, naming_convention=_NAMING
    ) as batch_op:
        batch_op.drop_constraint("uq_import_drafts_source_ref", type_="unique")
        batch_op.create_index(
            "uq_import_drafts_active_source_ref",
            ["source_ref"],
            unique=True,
            sqlite_where=sa.text("status IN ('pending', 'confirmed')"),
        )


def downgrade() -> None:
    """Restore global UNIQUE(source_ref) and remove the partial unique index."""
    with op.batch_alter_table(
        "import_drafts", schema=None, naming_convention=_NAMING
    ) as batch_op:
        batch_op.drop_index(
            "uq_import_drafts_active_source_ref",
            sqlite_where=sa.text("status IN ('pending', 'confirmed')"),
        )
        batch_op.create_unique_constraint("uq_import_drafts_source_ref", ["source_ref"])
