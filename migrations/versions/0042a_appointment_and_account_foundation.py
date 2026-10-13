"""appointment and account foundation"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0042a'
down_revision = '0041e'
branch_labels = None
depends_on = None


def upgrade():
    # Scalar user IDs share a GiST exclusion index with half-open timestamp ranges.
    op.execute('CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public')
    op.add_column('application_state', sa.Column('calendar_revision', sa.BigInteger(), server_default='0', nullable=False))
    op.create_table('academic_period',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('timezone', sa.String(length=100), nullable=False),
    sa.CheckConstraint('start_date <= end_date'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('appointment',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('organizer_id', sa.Integer(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('duration_minutes', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("end_at = start_at + duration_minutes * interval '1 minute'"),
    sa.CheckConstraint("status IN ('Pending Approval','Declined','Confirmed','Cancelled')"),
    sa.CheckConstraint('revision > 0 AND duration_minutes > 0 AND start_at < end_at'),
    sa.ForeignKeyConstraint(['organizer_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_appointment_organizer_start', 'appointment', ['organizer_id', 'start_at'], unique=False)
    op.create_table('calendar_block',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.CheckConstraint('start_at < end_at'),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_calendar_block_user_start', 'calendar_block', ['user_id', 'start_at'], unique=False)
    op.create_table('login_account',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('administrator', sa.Boolean(), nullable=False),
    sa.Column('session_version', sa.Integer(), nullable=False),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('failed_attempts >= 0 AND session_version > 0'),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('user_id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('professor_availability',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Integer(), nullable=False),
    sa.Column('start_minutes', sa.Integer(), nullable=False),
    sa.Column('end_minutes', sa.Integer(), nullable=False),
    sa.Column('valid_from', sa.Date(), nullable=False),
    sa.Column('valid_until', sa.Date(), nullable=False),
    sa.Column('timezone', sa.String(length=100), nullable=False),
    sa.Column('excluded_dates', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint('day BETWEEN 1 AND 7'),
    sa.CheckConstraint('start_minutes >= 0 AND start_minutes < end_minutes AND end_minutes <= 1440'),
    sa.CheckConstraint('valid_from <= valid_until'),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_professor_availability_user_id'), 'professor_availability', ['user_id'], unique=False)
    op.create_table('appointment_commitment',
    sa.Column('appointment_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period', postgresql.TSTZRANGE(), sa.Computed("tstzrange(start_at, end_at, '[)')", persisted=True), nullable=False),
    postgresql.ExcludeConstraint((sa.column('user_id'), '='), (sa.column('period'), '&&'), using='gist', name='ex_appointment_person_overlap'),
    sa.CheckConstraint('start_at < end_at'),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointment.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('appointment_id', 'user_id')
    )
    op.create_table('appointment_event',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('appointment_id', sa.BigInteger(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('revision > 0'),
    sa.ForeignKeyConstraint(['actor_id'], ['university_user.id'], ),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointment.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_appointment_event_appointment_id'), 'appointment_event', ['appointment_id'], unique=False)
    op.create_index('ix_appointment_event_actor_id', 'appointment_event', ['actor_id'], unique=False)
    op.create_table('appointment_invitation',
    sa.Column('appointment_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.CheckConstraint("status IN ('Invited','Declined')"),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointment.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('appointment_id', 'user_id')
    )
    op.create_index(op.f('ix_appointment_invitation_user_id'), 'appointment_invitation', ['user_id'], unique=False)
    op.create_table('appointment_professor',
    sa.Column('appointment_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.CheckConstraint("decision IN ('Pending','Approved','Declined')"),
    sa.CheckConstraint('revision > 0'),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointment.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['university_user.id'], ),
    sa.PrimaryKeyConstraint('appointment_id', 'user_id')
    )
    op.create_index(op.f('ix_appointment_professor_user_id'), 'appointment_professor', ['user_id'], unique=False)
    op.create_table('legacy_calendar_binding',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('period_id', sa.Integer(), nullable=False),
    sa.Column('busy_slot_id', sa.Integer(), nullable=True),
    sa.Column('request_id', sa.Integer(), nullable=True),
    sa.Column('week_start', sa.Date(), nullable=True),
    sa.Column('excluded_dates', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint('(busy_slot_id IS NULL) <> (request_id IS NULL)'),
    sa.ForeignKeyConstraint(['busy_slot_id'], ['busy_slot.id'], ),
    sa.ForeignKeyConstraint(['period_id'], ['academic_period.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['resource_request.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('period_id', 'busy_slot_id'),
    sa.UniqueConstraint('period_id', 'request_id')
    )
    op.create_index(op.f('ix_legacy_calendar_binding_busy_slot_id'), 'legacy_calendar_binding', ['busy_slot_id'], unique=False)
    op.create_index(op.f('ix_legacy_calendar_binding_period_id'), 'legacy_calendar_binding', ['period_id'], unique=False)
    op.create_index(op.f('ix_legacy_calendar_binding_request_id'), 'legacy_calendar_binding', ['request_id'], unique=False)


def downgrade():
    # Deliberately retain the shared extension; unrelated schemas may depend on it.
    op.drop_index(op.f('ix_legacy_calendar_binding_request_id'), table_name='legacy_calendar_binding')
    op.drop_index(op.f('ix_legacy_calendar_binding_period_id'), table_name='legacy_calendar_binding')
    op.drop_index(op.f('ix_legacy_calendar_binding_busy_slot_id'), table_name='legacy_calendar_binding')
    op.drop_table('legacy_calendar_binding')
    op.drop_index(op.f('ix_appointment_professor_user_id'), table_name='appointment_professor')
    op.drop_table('appointment_professor')
    op.drop_index(op.f('ix_appointment_invitation_user_id'), table_name='appointment_invitation')
    op.drop_table('appointment_invitation')
    op.drop_index('ix_appointment_event_actor_id', table_name='appointment_event')
    op.drop_index(op.f('ix_appointment_event_appointment_id'), table_name='appointment_event')
    op.drop_table('appointment_event')
    op.drop_table('appointment_commitment')
    op.drop_index(op.f('ix_professor_availability_user_id'), table_name='professor_availability')
    op.drop_table('professor_availability')
    op.drop_table('login_account')
    op.drop_index('ix_calendar_block_user_start', table_name='calendar_block')
    op.drop_table('calendar_block')
    op.drop_index('ix_appointment_organizer_start', table_name='appointment')
    op.drop_table('appointment')
    op.drop_table('academic_period')
    op.drop_column('application_state', 'calendar_revision')
