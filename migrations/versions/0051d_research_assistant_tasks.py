"""Add private research assistant planning tasks."""
from alembic import op
import sqlalchemy as sa


revision = "0051d"
down_revision = "0051c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("research_task",
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("university_user.id"), primary_key=True, autoincrement=False),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("char_length(btrim(title)) > 0", name="ck_research_task_title"),
        sa.CheckConstraint("revision > 0", name="ck_research_task_revision"))

def downgrade():
    op.execute("LOCK TABLE research_task IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM research_task)")):
        raise RuntimeError("Cannot discard saved research tasks. Keep this migration to preserve personal planning data.")
    op.drop_table("research_task")
