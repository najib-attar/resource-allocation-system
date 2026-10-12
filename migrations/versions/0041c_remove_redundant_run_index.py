"""The decision and run/engine indexes already cover the allocation run prefix."""

from alembic import op

revision = "0041c"
down_revision = "0041b"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_allocation_run_id", table_name="allocation")


def downgrade():
    op.create_index("ix_allocation_run_id", "allocation", ["run_id"])
