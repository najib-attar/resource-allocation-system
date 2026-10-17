"""Opt-in academic calendar publication; existing records remain private."""
from alembic import op
import sqlalchemy as sa

revision = '0045a'
down_revision = '0044c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('resource_request', sa.Column('calendar_public', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('resource_request', sa.Column('academic_instructor_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_calendar_instructor', 'resource_request', 'university_user', ['academic_instructor_id'], ['id'])
    op.create_index('ix_resource_request_academic_instructor_id', 'resource_request', ['academic_instructor_id'])
    op.create_check_constraint('ck_calendar_public_request_type', 'resource_request', "NOT calendar_public OR type <> 'CommitteeMeeting'")


def downgrade():
    op.drop_constraint('ck_calendar_public_request_type', 'resource_request', type_='check')
    op.drop_index('ix_resource_request_academic_instructor_id', table_name='resource_request')
    op.drop_constraint('fk_calendar_instructor', 'resource_request', type_='foreignkey')
    op.drop_column('resource_request', 'academic_instructor_id')
    op.drop_column('resource_request', 'calendar_public')
