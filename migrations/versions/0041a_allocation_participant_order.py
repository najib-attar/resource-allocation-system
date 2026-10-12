"""Preserve engine participant order in persisted allocation results."""

from alembic import op
import sqlalchemy as sa

revision = "0041a"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("allocation_participant", sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("allocation_participant", "ordinal")
