"""student room requests and faculty policies"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0043a'
down_revision = '0042b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('room_closure',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.CheckConstraint('start_at < end_at'),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_room_closure_resource_start', 'room_closure', ['resource_id', 'start_at'], unique=False)
    op.create_table('room_policy',
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('faculty_id', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('restricted', sa.Boolean(), nullable=False),
    sa.Column('categories', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint('jsonb_typeof(categories) = \'array\' AND jsonb_array_length(categories) BETWEEN 1 AND 5 AND \'["study","meeting","lecture","club","other"]\'::jsonb @> categories'),
    sa.ForeignKeyConstraint(['faculty_id'], ['organization_unit.id'], ),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
    sa.PrimaryKeyConstraint('resource_id')
    )
    op.create_index(op.f('ix_room_policy_faculty_id'), 'room_policy', ['faculty_id'], unique=False)
    op.create_table('room_access',
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['resource_id'], ['room_policy.resource_id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('resource_id', 'user_id')
    )
    op.create_index(op.f('ix_room_access_user_id'), 'room_access', ['user_id'], unique=False)
    op.create_table('faculty_room_approver',
    sa.Column('faculty_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['faculty_id'], ['organization_unit.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['login_account.user_id'], ),
    sa.PrimaryKeyConstraint('faculty_id')
    )
    op.create_index(op.f('ix_faculty_room_approver_user_id'), 'faculty_room_approver', ['user_id'], unique=False)
    op.create_table('student_room_request',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('organizer_id', sa.Integer(), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('faculty_id', sa.Integer(), nullable=False),
    sa.Column('approver_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('club_affiliation', sa.Text(), nullable=False),
    sa.Column('attendee_count', sa.Integer(), nullable=False),
    sa.Column('required_features', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('preferred_faculty_id', sa.Integer(), nullable=True),
    sa.Column('preferred_building', sa.Text(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_minutes', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('approved_revision', sa.Integer(), nullable=True),
    sa.Column('approved_by', sa.Integer(), nullable=True),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category IN ('study','meeting','lecture','club','other')"),
    sa.CheckConstraint("end_at = start_at + duration_minutes * interval '1 minute'"),
    sa.CheckConstraint("status <> 'Confirmed' OR (approved_revision IS NOT NULL AND approved_revision = revision AND approved_by IS NOT NULL AND approved_by = approver_id)"),
    sa.CheckConstraint("status IN ('Pending Faculty Approval','Needs Revision','Rejected','Confirmed','Cancelled')"),
    sa.CheckConstraint('jsonb_typeof(required_features) = \'array\' AND \'["projector","whiteboard","computers"]\'::jsonb @> required_features'),
    sa.CheckConstraint('revision > 0 AND attendee_count > 0 AND duration_minutes BETWEEN 1 AND 1440 AND start_at < end_at'),
    sa.ForeignKeyConstraint(['approved_by'], ['login_account.user_id'], ),
    sa.ForeignKeyConstraint(['approver_id'], ['login_account.user_id'], ),
    sa.ForeignKeyConstraint(['faculty_id'], ['organization_unit.id'], ),
    sa.ForeignKeyConstraint(['organizer_id'], ['university_user.id'], ),
    sa.ForeignKeyConstraint(['preferred_faculty_id'], ['organization_unit.id'], ),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_student_room_approver_status', 'student_room_request', ['approver_id', 'status'], unique=False)
    op.create_index('ix_student_room_organizer_start', 'student_room_request', ['organizer_id', 'start_at'], unique=False)
    op.create_index(op.f('ix_student_room_request_approved_by'), 'student_room_request', ['approved_by'], unique=False)
    op.create_index(op.f('ix_student_room_request_faculty_id'), 'student_room_request', ['faculty_id'], unique=False)
    op.create_index(op.f('ix_student_room_request_preferred_faculty_id'), 'student_room_request', ['preferred_faculty_id'], unique=False)
    op.create_index(op.f('ix_student_room_request_resource_id'), 'student_room_request', ['resource_id'], unique=False)
    op.create_table('room_event',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('request_id', sa.BigInteger(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('revision > 0'),
    sa.ForeignKeyConstraint(['actor_id'], ['university_user.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['student_room_request.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_room_event_actor_id'), 'room_event', ['actor_id'], unique=False)
    op.create_index(op.f('ix_room_event_request_id'), 'room_event', ['request_id'], unique=False)
    op.create_table('room_invitation',
    sa.Column('request_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.CheckConstraint("status IN ('Invited','Accepted','Declined')"),
    sa.CheckConstraint('revision > 0'),
    sa.ForeignKeyConstraint(['request_id'], ['student_room_request.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('request_id', 'user_id')
    )
    op.create_index(op.f('ix_room_invitation_user_id'), 'room_invitation', ['user_id'], unique=False)
    op.create_table('room_organizer_commitment',
    sa.Column('request_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period', postgresql.TSTZRANGE(), sa.Computed("tstzrange(start_at, end_at, '[)')", persisted=True), nullable=False),
    postgresql.ExcludeConstraint((sa.column('user_id'), '='), (sa.column('period'), '&&'), using='gist', name='ex_room_organizer_overlap'),
    sa.CheckConstraint('start_at < end_at'),
    sa.ForeignKeyConstraint(['request_id'], ['student_room_request.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('request_id')
    )
    op.create_index(op.f('ix_room_organizer_commitment_user_id'), 'room_organizer_commitment', ['user_id'], unique=False)
    op.create_table('room_reservation',
    sa.Column('request_id', sa.BigInteger(), nullable=False),
    sa.Column('resource_id', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period', postgresql.TSTZRANGE(), sa.Computed("tstzrange(start_at, end_at, '[)')", persisted=True), nullable=False),
    postgresql.ExcludeConstraint((sa.column('resource_id'), '='), (sa.column('period'), '&&'), using='gist', name='ex_student_room_overlap'),
    sa.CheckConstraint('start_at < end_at'),
    sa.ForeignKeyConstraint(['request_id'], ['student_room_request.id'], ),
    sa.ForeignKeyConstraint(['resource_id'], ['resource.id'], ),
    sa.PrimaryKeyConstraint('request_id')
    )
    op.create_index(op.f('ix_room_reservation_resource_id'), 'room_reservation', ['resource_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_room_reservation_resource_id'), table_name='room_reservation')
    op.drop_table('room_reservation')
    op.drop_index(op.f('ix_room_organizer_commitment_user_id'), table_name='room_organizer_commitment')
    op.drop_table('room_organizer_commitment')
    op.drop_index(op.f('ix_room_invitation_user_id'), table_name='room_invitation')
    op.drop_table('room_invitation')
    op.drop_index(op.f('ix_room_event_request_id'), table_name='room_event')
    op.drop_index(op.f('ix_room_event_actor_id'), table_name='room_event')
    op.drop_table('room_event')
    op.drop_index(op.f('ix_student_room_request_resource_id'), table_name='student_room_request')
    op.drop_index(op.f('ix_student_room_request_preferred_faculty_id'), table_name='student_room_request')
    op.drop_index(op.f('ix_student_room_request_faculty_id'), table_name='student_room_request')
    op.drop_index(op.f('ix_student_room_request_approved_by'), table_name='student_room_request')
    op.drop_index('ix_student_room_organizer_start', table_name='student_room_request')
    op.drop_index('ix_student_room_approver_status', table_name='student_room_request')
    op.drop_table('student_room_request')
    op.drop_index(op.f('ix_faculty_room_approver_user_id'), table_name='faculty_room_approver')
    op.drop_table('faculty_room_approver')
    op.drop_index(op.f('ix_room_access_user_id'), table_name='room_access')
    op.drop_table('room_access')
    op.drop_index(op.f('ix_room_policy_faculty_id'), table_name='room_policy')
    op.drop_table('room_policy')
    op.drop_index('ix_room_closure_resource_start', table_name='room_closure')
    op.drop_table('room_closure')
