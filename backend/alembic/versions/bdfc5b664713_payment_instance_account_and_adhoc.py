"""payment_instance_account_and_adhoc

Revision ID: bdfc5b664713
Revises: 7062d8fe6543
Create Date: 2026-11-26 10:35:14.083772

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "bdfc5b664713"
down_revision: Union[str, Sequence[str], None] = "7062d8fe6543"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("payment_instances", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("account_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("label", sa.Text(), nullable=True))
        batch_op.alter_column("bill_id", existing_type=sa.INTEGER(), nullable=True)
        batch_op.create_index(
            batch_op.f("ix_payment_instances_user_id"), ["user_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_payment_instances_user_id", "users", ["user_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_payment_instances_account_id",
            "bank_accounts",
            ["account_id"],
            ["id"],
        )

    op.execute(
        sa.text(
            "UPDATE payment_instances "
            "SET user_id = ("
            "  SELECT user_id FROM bill_templates "
            "  WHERE bill_templates.id = payment_instances.bill_id"
            ") "
            "WHERE bill_id IS NOT NULL AND user_id IS NULL"
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("payment_instances", schema=None) as batch_op:
        batch_op.drop_constraint("fk_payment_instances_account_id", type_="foreignkey")
        batch_op.drop_constraint("fk_payment_instances_user_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_payment_instances_user_id"))
        batch_op.alter_column("bill_id", existing_type=sa.INTEGER(), nullable=False)
        batch_op.drop_column("label")
        batch_op.drop_column("account_id")
        batch_op.drop_column("user_id")
