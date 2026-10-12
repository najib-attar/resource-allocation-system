"""initial PostgreSQL weekly application schema"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0041'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('allocation_run',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('correlation_id', sa.String(length=32), nullable=False),
    sa.Column('input_revision', sa.BigInteger(), nullable=False),
    sa.Column('strategy', sa.String(length=50), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('build', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('engine_version', sa.Text(), nullable=False),
    sa.Column('error', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('running','success','failed','superseded')"),
    sa.CheckConstraint("strategy IN ('greedy','priority','multi_room_exam_greedy','multi_room_exam_best_fit','shared_room_exam_best_fit')"),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('correlation_id')
    )
    op.create_index(op.f('ix_allocation_run_status'), 'allocation_run', ['status'], unique=False)
    op.create_table('organization_unit',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('unit_type', sa.String(length=100), nullable=True),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id'),
    sa.ForeignKeyConstraint(['parent_id'], ['organization_unit.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_organization_unit_parent_id'), 'organization_unit', ['parent_id'], unique=False)
    op.create_table('resource',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('source_order', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('building', sa.Text(), nullable=False),
    sa.Column('projector', sa.Boolean(), nullable=False),
    sa.Column('whiteboard', sa.Boolean(), nullable=False),
    sa.Column('computers', sa.Boolean(), nullable=False),
    sa.Column('available', sa.Boolean(), nullable=False),
    sa.CheckConstraint("type IN ('Classroom','Laboratory','MeetingRoom')"),
    sa.CheckConstraint('id > 0 AND capacity > 0'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_order')
    )
    op.create_table('role',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('application_state',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('input_revision', sa.BigInteger(), nullable=False),
    sa.Column('strategy', sa.String(length=50), nullable=False),
    sa.Column('active_run_id', sa.BigInteger(), nullable=True),
    sa.CheckConstraint("strategy IN ('greedy','priority','multi_room_exam_greedy','multi_room_exam_best_fit','shared_room_exam_best_fit')"),
    sa.CheckConstraint('id = 1 AND input_revision >= 0'),
    sa.ForeignKeyConstraint(['active_run_id'], ['allocation_run.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('university_user',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('source_order', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('primary_role_id', sa.Integer(), nullable=False),
    sa.Column('primary_unit_id', sa.Integer(), nullable=True),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('student_no', sa.Text(), nullable=False),
    sa.Column('program', sa.Text(), nullable=False),
    sa.Column('year_level', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('office_room', sa.Text(), nullable=False),
    sa.Column('assistant_type', sa.Text(), nullable=False),
    sa.Column('job_title', sa.Text(), nullable=False),
    sa.Column('admin_level', sa.Text(), nullable=False),
    sa.CheckConstraint('id > 0'),
    sa.CheckConstraint('year_level >= 0'),
    sa.ForeignKeyConstraint(['primary_role_id'], ['role.id'], ),
    sa.ForeignKeyConstraint(['primary_unit_id'], ['organization_unit.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_order')
    )
    op.create_index(op.f('ix_university_user_primary_role_id'), 'university_user', ['primary_role_id'], unique=False)
    op.create_index(op.f('ix_university_user_primary_unit_id'), 'university_user', ['primary_unit_id'], unique=False)
    op.create_table('busy_slot',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('source_order', sa.Integer(), nullable=False),
    sa.Column('day', sa.Integer(), nullable=False),
    sa.Column('start_minutes', sa.Integer(), nullable=False),
    sa.Column('end_minutes', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.CheckConstraint('day BETWEEN 1 AND 7'),
    sa.CheckConstraint('start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440'),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_order')
    )
    op.create_index(op.f('ix_busy_slot_user_id'), 'busy_slot', ['user_id'], unique=False)
    op.create_table('resource_request',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('submission_order', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('requester_id', sa.Integer(), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('participant_count', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('required_feature', sa.Text(), nullable=False),
    sa.Column('required_building', sa.Text(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.CheckConstraint("type IN ('OneTime','Recurring','Exam','CommitteeMeeting')"),
    sa.CheckConstraint('id > 0 AND participant_count > 0 AND revision > 0'),
    sa.ForeignKeyConstraint(['requester_id'], ['university_user.id'], ),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('submission_order')
    )
    op.create_index(op.f('ix_resource_request_requester_id'), 'resource_request', ['requester_id'], unique=False)
    op.create_index(op.f('ix_resource_request_resource_id'), 'resource_request', ['resource_id'], unique=False)
    op.create_table('user_role',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role_id', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['role.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('user_id', 'role_id'),
    sa.UniqueConstraint('user_id', 'ordinal')
    )
    op.create_table('exam_details',
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('course_code', sa.Text(), nullable=False),
    sa.Column('course_name', sa.Text(), nullable=False),
    sa.Column('exam_type', sa.Text(), nullable=False),
    sa.Column('can_split', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['request_id'], ['resource_request.id'], ),
    sa.PrimaryKeyConstraint('request_id')
    )
    op.create_table('request_decision',
    sa.Column('run_id', sa.BigInteger(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("status IN ('Approved','Rejected')"),
    sa.ForeignKeyConstraint(['request_id'], ['resource_request.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['allocation_run.id'], ),
    sa.PrimaryKeyConstraint('run_id', 'request_id')
    )
    op.create_table('request_history',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.BigInteger(), nullable=True),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['request_id'], ['resource_request.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['allocation_run.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_request_history_request_id'), 'request_history', ['request_id'], unique=False)
    op.create_index(op.f('ix_request_history_run_id'), 'request_history', ['run_id'], unique=False)
    op.create_table('request_participant',
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['request_id'], ['resource_request.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('request_id', 'user_id'),
    sa.UniqueConstraint('request_id', 'ordinal')
    )
    op.create_table('request_slot',
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('day', sa.Integer(), nullable=False),
    sa.Column('start_minutes', sa.Integer(), nullable=False),
    sa.Column('end_minutes', sa.Integer(), nullable=False),
    sa.CheckConstraint('day BETWEEN 1 AND 7'),
    sa.CheckConstraint('start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440'),
    sa.ForeignKeyConstraint(['request_id'], ['resource_request.id'], ),
    sa.PrimaryKeyConstraint('request_id', 'ordinal')
    )
    op.create_table('allocation',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('run_id', sa.BigInteger(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('engine_id', sa.Integer(), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Integer(), nullable=False),
    sa.Column('start_minutes', sa.Integer(), nullable=False),
    sa.Column('end_minutes', sa.Integer(), nullable=False),
    sa.Column('assigned_participants', sa.Integer(), nullable=False),
    sa.CheckConstraint('assigned_participants > 0'),
    sa.CheckConstraint('day BETWEEN 1 AND 7'),
    sa.CheckConstraint('start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440'),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
    sa.ForeignKeyConstraint(['run_id', 'request_id'], ['request_decision.run_id', 'request_decision.request_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'engine_id')
    )
    op.create_index(op.f('ix_allocation_request_id'), 'allocation', ['request_id'], unique=False)
    op.create_index(op.f('ix_allocation_resource_id'), 'allocation', ['resource_id'], unique=False)
    op.create_index(op.f('ix_allocation_run_id'), 'allocation', ['run_id'], unique=False)
    op.create_table('suggestion_group',
    sa.Column('run_id', sa.BigInteger(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['run_id', 'request_id'], ['request_decision.run_id', 'request_decision.request_id'], ),
    sa.PrimaryKeyConstraint('run_id', 'request_id')
    )
    op.create_table('allocation_participant',
    sa.Column('allocation_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['allocation_id'], ['allocation.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('allocation_id', 'user_id')
    )
    op.create_table('meeting_suggestion',
    sa.Column('run_id', sa.BigInteger(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Integer(), nullable=False),
    sa.Column('start_minutes', sa.Integer(), nullable=False),
    sa.Column('end_minutes', sa.Integer(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('time_distance', sa.Integer(), nullable=False),
    sa.Column('day_distance', sa.Integer(), nullable=False),
    sa.Column('conflict_count', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.CheckConstraint('day BETWEEN 1 AND 7'),
    sa.CheckConstraint('start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440'),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
    sa.ForeignKeyConstraint(['run_id', 'request_id'], ['suggestion_group.run_id', 'suggestion_group.request_id'], ),
    sa.PrimaryKeyConstraint('run_id', 'request_id', 'rank')
    )
    op.bulk_insert(sa.table('application_state', sa.column('id'), sa.column('input_revision'), sa.column('strategy')),
                   [{'id': 1, 'input_revision': 0, 'strategy': 'greedy'}])


def downgrade():
    op.drop_table('meeting_suggestion')
    op.drop_table('allocation_participant')
    op.drop_table('suggestion_group')
    op.drop_index(op.f('ix_allocation_run_id'), table_name='allocation')
    op.drop_index(op.f('ix_allocation_resource_id'), table_name='allocation')
    op.drop_index(op.f('ix_allocation_request_id'), table_name='allocation')
    op.drop_table('allocation')
    op.drop_table('request_slot')
    op.drop_table('request_participant')
    op.drop_index(op.f('ix_request_history_run_id'), table_name='request_history')
    op.drop_index(op.f('ix_request_history_request_id'), table_name='request_history')
    op.drop_table('request_history')
    op.drop_table('request_decision')
    op.drop_table('exam_details')
    op.drop_table('user_role')
    op.drop_index(op.f('ix_resource_request_resource_id'), table_name='resource_request')
    op.drop_index(op.f('ix_resource_request_requester_id'), table_name='resource_request')
    op.drop_table('resource_request')
    op.drop_index(op.f('ix_busy_slot_user_id'), table_name='busy_slot')
    op.drop_table('busy_slot')
    op.drop_index(op.f('ix_university_user_primary_unit_id'), table_name='university_user')
    op.drop_index(op.f('ix_university_user_primary_role_id'), table_name='university_user')
    op.drop_table('university_user')
    op.drop_table('application_state')
    op.drop_table('role')
    op.drop_table('resource')
    op.drop_index(op.f('ix_organization_unit_parent_id'), table_name='organization_unit')
    op.drop_table('organization_unit')
    op.drop_index(op.f('ix_allocation_run_status'), table_name='allocation_run')
    op.drop_table('allocation_run')
