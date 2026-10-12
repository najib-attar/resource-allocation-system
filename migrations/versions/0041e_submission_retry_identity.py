"""Optional persisted identity for exact form retries, without another table."""

from alembic import op
import sqlalchemy as sa

revision = "0041e"
down_revision = "0041d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("resource_request", sa.Column("submission_key", sa.String(32), nullable=True))
    op.add_column("resource_request", sa.Column("submission_fingerprint", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_resource_request_submission_key", "resource_request", ["submission_key"])
    op.create_check_constraint("ck_submission_identity", "resource_request", "(submission_key IS NULL AND submission_fingerprint IS NULL) OR (submission_key IS NOT NULL AND submission_fingerprint IS NOT NULL AND submission_key ~ '^[0-9a-f]{32}$' AND submission_fingerprint ~ '^[0-9a-f]{64}$')")


def downgrade():
    op.drop_constraint("ck_submission_identity", "resource_request", type_="check")
    op.drop_constraint("uq_resource_request_submission_key", "resource_request", type_="unique")
    op.drop_column("resource_request", "submission_fingerprint")
    op.drop_column("resource_request", "submission_key")
