"""Private shared resource feedback and explicit student group registration."""
from alembic import op
import sqlalchemy as sa

revision = '0048a'
down_revision = '0047a'
branch_labels = None
depends_on = None


def participant_rule(forward):
    connection = op.get_bind()
    definition = connection.scalar(sa.text("SELECT pg_get_functiondef('ras_room_shape(bigint)'::regprocedure)"))
    old = "p.name<>'Instructor'"
    new = "(p.name NOT IN ('Instructor','Student') OR (p.name='Student' AND i.status<>'Accepted'))"
    source, target = (old, new) if forward else (new, old)
    if source not in definition:
        raise RuntimeError('Unexpected room integrity function; review migration before proceeding.')
    definition = definition.replace(source, target)
    marker = 'IF NOT FOUND THEN RETURN; END IF;'
    checked = marker + "\n        IF r.attendee_count < 1 + (SELECT count(*) FROM room_invitation WHERE request_id=k) THEN\n            RAISE EXCEPTION 'Declared attendees must include all registered participants' USING ERRCODE='23514';\n        END IF;"
    definition = definition.replace(marker, checked) if forward else definition.replace(checked, marker)
    op.execute(definition)
    if forward:
        op.execute('SELECT ras_room_shape(id) FROM student_room_request')


def upgrade():
    participant_rule(True)
    op.create_table('resource_feedback',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('room_request_id', sa.BigInteger(), sa.ForeignKey('student_room_request.id')),
        sa.Column('room_resource_id', sa.Integer(), sa.ForeignKey('resource.id')),
        sa.Column('room_revision', sa.Integer()),
        sa.Column('equipment_reservation_id', sa.Integer(), sa.ForeignKey('equipment_reservation.id')),
        sa.Column('reporter_id', sa.Integer(), sa.ForeignKey('university_user.id'), nullable=False),
        sa.Column('faculty_id', sa.Integer(), sa.ForeignKey('organization_unit.id'), nullable=False),
        sa.Column('assigned_to_id', sa.Integer(), sa.ForeignKey('login_account.user_id'), nullable=False),
        sa.Column('category', sa.String(20), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('priority', sa.String(10), nullable=False),
        sa.Column('response', sa.Text(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('submission_key', sa.String(32), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.CheckConstraint('(room_request_id IS NOT NULL AND room_resource_id IS NOT NULL AND room_revision IS NOT NULL AND room_revision > 0 AND equipment_reservation_id IS NULL) OR (room_request_id IS NULL AND room_resource_id IS NULL AND room_revision IS NULL AND equipment_reservation_id IS NOT NULL)', name='ck_feedback_usage'),
        sa.CheckConstraint("category IN ('problem','improvement','general')"),
        sa.CheckConstraint("status IN ('Submitted','Under Review','Resolved','Closed')"),
        sa.CheckConstraint("priority IN ('low','normal','high','urgent')"),
        sa.CheckConstraint('length(btrim(description)) BETWEEN 1 AND 4000 AND length(response) <= 4000 AND revision > 0'),
        sa.CheckConstraint("submission_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$'"),
        sa.UniqueConstraint('reporter_id', 'submission_key'))
    for column in ('room_request_id', 'room_resource_id', 'equipment_reservation_id', 'assigned_to_id'):
        op.create_index('ix_resource_feedback_'+column, 'resource_feedback', [column])
    op.create_index('ix_feedback_faculty_status', 'resource_feedback', ['faculty_id', 'status', 'id'])
    op.create_index('ix_feedback_reporter_created', 'resource_feedback', ['reporter_id', 'created_at', 'id'])
    op.create_table('feedback_event',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('report_id', sa.BigInteger(), sa.ForeignKey('resource_feedback.id'), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('university_user.id'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('action_key', sa.String(32), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.UniqueConstraint('report_id', 'action_key'), sa.UniqueConstraint('report_id', 'revision'),
        sa.CheckConstraint('revision > 0 AND length(btrim(message)) BETWEEN 1 AND 4500'),
        sa.CheckConstraint("status IN ('Submitted','Under Review','Resolved','Closed')"),
        sa.CheckConstraint("action_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$'"))
    for column in ('report_id', 'actor_id'):
        op.create_index('ix_feedback_event_'+column, 'feedback_event', [column])
    op.add_column('notification', sa.Column('feedback_event_id', sa.BigInteger(), sa.ForeignKey('feedback_event.id')))
    op.create_index('ix_notification_feedback_event_id', 'notification', ['feedback_event_id'])
    op.create_unique_constraint('uq_notification_recipient_feedback', 'notification', ['recipient_id', 'feedback_event_id'])
    op.drop_constraint('ck_notification_source', 'notification', type_='check')
    op.create_check_constraint('ck_notification_source', 'notification', 'num_nonnulls(appointment_event_id, room_event_id, equipment_event_id, feedback_event_id) = 1')
    op.execute("""
    CREATE FUNCTION ras_feedback_shape() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='UPDATE' THEN
        IF ROW(NEW.room_request_id,NEW.room_resource_id,NEW.room_revision,NEW.equipment_reservation_id,NEW.reporter_id,NEW.faculty_id,NEW.category,NEW.description,NEW.submission_key,NEW.fingerprint,NEW.created_at)
          IS DISTINCT FROM ROW(OLD.room_request_id,OLD.room_resource_id,OLD.room_revision,OLD.equipment_reservation_id,OLD.reporter_id,OLD.faculty_id,OLD.category,OLD.description,OLD.submission_key,OLD.fingerprint,OLD.created_at) THEN
          RAISE EXCEPTION 'Feedback usage and original submission are immutable' USING ERRCODE='23514';
        END IF;
      ELSIF NEW.room_request_id IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM student_room_request r WHERE r.id=NEW.room_request_id AND r.status='Confirmed'
          AND r.resource_id=NEW.room_resource_id AND r.faculty_id=NEW.faculty_id AND r.revision=NEW.room_revision
          AND (r.organizer_id=NEW.reporter_id OR EXISTS(SELECT 1 FROM room_invitation i WHERE i.request_id=r.id AND i.user_id=NEW.reporter_id AND i.revision=r.revision AND i.status='Accepted'))) THEN
          RAISE EXCEPTION 'Feedback requires an actual confirmed room association' USING ERRCODE='23514';
        END IF;
      ELSE
        IF NOT EXISTS (SELECT 1 FROM equipment_reservation e JOIN borrow_item i ON i.id=e.item_id JOIN borrow_request b ON b.id=i.request_id
          WHERE e.id=NEW.equipment_reservation_id AND e.handed_at IS NOT NULL AND b.borrower_id=NEW.reporter_id AND b.faculty_id=NEW.faculty_id) THEN
          RAISE EXCEPTION 'Feedback requires an actual handed-over loan association' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER resource_feedback_shape BEFORE INSERT OR UPDATE ON resource_feedback FOR EACH ROW EXECUTE FUNCTION ras_feedback_shape();
    """)


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text('SELECT EXISTS(SELECT 1 FROM resource_feedback)')) or connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM room_invitation i JOIN university_user u ON u.id=i.user_id JOIN role r ON r.id=u.primary_role_id WHERE r.name='Student')")):
        raise RuntimeError('Downgrade would remove reports or student registrations. Export and review that data explicitly first.')
    op.execute('DROP TRIGGER resource_feedback_shape ON resource_feedback; DROP FUNCTION ras_feedback_shape()')
    op.drop_constraint('ck_notification_source', 'notification', type_='check')
    op.drop_constraint('uq_notification_recipient_feedback', 'notification', type_='unique')
    op.drop_index('ix_notification_feedback_event_id', table_name='notification')
    op.drop_column('notification', 'feedback_event_id')
    op.create_check_constraint('ck_notification_source', 'notification', 'num_nonnulls(appointment_event_id, room_event_id, equipment_event_id) = 1')
    op.drop_table('feedback_event')
    op.drop_table('resource_feedback')
    participant_rule(False)
