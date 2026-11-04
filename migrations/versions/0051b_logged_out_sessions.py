"""Reject replay of logged-out signed sessions, including delayed responses."""

from alembic import op
import sqlalchemy as sa


revision = '0051b'
down_revision = '0051a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('logged_out_session',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('university_user.id'), primary_key=True),
        sa.Column('session_version', sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column('token_digest', sa.String(64), primary_key=True),
        sa.Column('logged_out_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('session_version > 0', name='ck_logout_session_version'),
        sa.CheckConstraint("token_digest ~ '^[0-9a-f]{64}$'", name='ck_logout_token_digest'))


def downgrade():
    # Discarding denials could reactivate cookies already presented to logout.
    op.execute("LOCK TABLE logged_out_session IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM logged_out_session)')):
        raise RuntimeError('Cannot discard logout revocations. Keep this migration and deploy matching authentication code.')
    op.drop_table('logged_out_session')
