"""one off bills are always fixed amount

Revision ID: 5b12c786c99c
Revises: 9357ad392685
Create Date: 2026-10-16 00:07:52.506171

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b12c786c99c"
down_revision: Union[str, Sequence[str], None] = "9357ad392685"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One-off bills are single known charges.

    A "usage-based" one-off has no future cycle to confirm an estimate
    against, and its estimated instance is invisible in the ledger (and in
    the review queue until its period arrives), which makes it unpayable.
    Clear the flag and un-estimate any instances so they surface normally.
    """
    op.execute(
        "UPDATE bill_templates SET amount_varies = 0 WHERE frequency = 'one_off'"
    )
    op.execute(
        "UPDATE payment_instances SET amount_estimated = 0 "
        "WHERE bill_id IN (SELECT id FROM bill_templates WHERE frequency = 'one_off')"
    )


def downgrade() -> None:
    """Data-only migration: the previous flag values are not recoverable."""
    pass
