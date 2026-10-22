"""Explicit semesters, selected-date decisions and auditable reservation priorities."""
from importlib import import_module
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0049b'
down_revision = '0049a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('academic_period', sa.Column('is_semester',sa.Boolean(),nullable=False,server_default='false'))
    op.add_column('application_state', sa.Column('recurring_limits', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column('application_state', sa.Column('reservation_priorities', JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    for table in ('student_room_request', 'borrow_request'):
        op.add_column(table, sa.Column('priority', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('reservation_series', sa.Column('period_id', sa.Integer(), sa.ForeignKey('academic_period.id')))
    op.create_index('ix_reservation_series_period_id', 'reservation_series', ['period_id'])
    op.add_column('reservation_series', sa.Column('approval_mode', sa.String(10), nullable=False, server_default='all'))
    op.create_check_constraint('ck_series_approval_mode', 'reservation_series', "approval_mode IN ('all','partial')")
    for check in sa.inspect(op.get_bind()).get_check_constraints('reservation_occurrence'):
        if 'status' in check['sqltext']:
            op.drop_constraint(check['name'], 'reservation_occurrence', type_='check')
    op.create_check_constraint('ck_occurrence_outcome', 'reservation_occurrence', "ordinal BETWEEN 1 AND 366 AND start_at < end_at AND status IN ('Proposed','Unavailable','Rejected','Reserved','Completed','Cancelled')")
    op.add_column('reservation_occurrence', sa.Column('explanation', sa.Text(), nullable=False, server_default=''))
    op.add_column('reservation_occurrence', sa.Column('decided_by', sa.Integer(), sa.ForeignKey('login_account.user_id')))
    op.add_column('reservation_occurrence', sa.Column('decided_at', sa.DateTime(timezone=True)))
    op.create_index('ix_reservation_occurrence_decided_by', 'reservation_occurrence', ['decided_by'])
    op.create_table('reservation_priority_override',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('room_request_id', sa.BigInteger(), sa.ForeignKey('student_room_request.id')),
        sa.Column('borrow_request_id', sa.Integer(), sa.ForeignKey('borrow_request.id')),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('login_account.user_id'), nullable=False),
        sa.Column('original_priority', sa.Integer(), nullable=False), sa.Column('selected_priority', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('transaction_id', sa.BigInteger(), nullable=False, server_default=sa.text('txid_current()')),
        sa.CheckConstraint('num_nonnulls(room_request_id, borrow_request_id) = 1'),
        sa.CheckConstraint('original_priority >= 0 AND selected_priority >= 0 AND original_priority <> selected_priority'),
        sa.CheckConstraint('length(btrim(reason)) BETWEEN 1 AND 2000'))
    for column in ('room_request_id', 'borrow_request_id', 'actor_id'):
        op.create_index('ix_reservation_priority_override_'+column, 'reservation_priority_override', [column])
    # Reuse the preceding complete-expansion/reservation checks, extending only
    # the approved occurrence-state policy rather than maintaining a second shape engine.
    original = import_module('migrations.versions.0049a_recurring_reservations').SERIES_INTEGRITY
    shape = original.split('CREATE FUNCTION ras_room_shape')[0].replace('CREATE FUNCTION ras_series_shape', 'CREATE OR REPLACE FUNCTION ras_series_shape')
    shape = shape.replace("status NOT IN ('Proposed','Cancelled')", "status NOT IN ('Proposed','Unavailable','Rejected','Cancelled')")
    shape = shape.replace("OR EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status NOT IN ('Reserved','Cancelled'))", "OR (s.approval_mode='all' AND EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status NOT IN ('Reserved','Cancelled')))")
    shape = shape.replace("OR o.status='Proposed'", "OR o.status IN ('Proposed','Unavailable','Rejected')")
    shape = shape.replace("(b.status IN ('Approved','Borrowed','Partially Returned','Returned') AND EXISTS", "(s.approval_mode='all' AND b.status IN ('Approved','Borrowed','Partially Returned','Returned') AND EXISTS")
    shape = shape.replace("AND EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status='Proposed'))", "AND EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status IN ('Proposed','Unavailable','Rejected')))")
    op.execute(shape)
    op.execute(GUARDS)


GUARDS = """
CREATE FUNCTION ras_recurring_policy_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p academic_period%ROWTYPE; s reservation_series%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='reservation_series' THEN
   IF TG_OP='UPDATE' AND ROW(NEW.period_id,NEW.approval_mode) IS DISTINCT FROM ROW(OLD.period_id,OLD.approval_mode)
     AND NOT (OLD.period_id IS NULL AND NEW.period_id IS NOT NULL AND OLD.approval_mode=NEW.approval_mode) THEN
     RAISE EXCEPTION 'Semester and approval consent are immutable' USING ERRCODE='23514';
   END IF;
   IF NEW.period_id IS NULL AND TG_OP='INSERT' THEN
     RAISE EXCEPTION 'An explicit academic semester is required' USING ERRCODE='23514';
   END IF;
   IF NEW.period_id IS NOT NULL THEN
     SELECT * INTO p FROM academic_period WHERE id=NEW.period_id FOR SHARE;
     IF NOT FOUND OR NOT p.is_semester OR NEW.timezone<>p.timezone OR NEW.start_date<p.start_date OR NEW.end_date>p.end_date
       OR EXISTS(SELECT 1 FROM reservation_occurrence o WHERE o.series_id=NEW.id
         AND o.end_at>((p.end_date+1)::timestamp AT TIME ZONE p.timezone)) THEN
       RAISE EXCEPTION 'Recurring dates must remain inside one configured semester' USING ERRCODE='23514';
     END IF;
   END IF;
 ELSIF TG_TABLE_NAME='borrow_extension' THEN
   SELECT * INTO s FROM reservation_series WHERE borrow_request_id=NEW.request_id;
   IF FOUND AND NEW.status='Approved' AND NOT EXISTS(SELECT 1 FROM academic_period ap WHERE ap.id=s.period_id
       AND ap.is_semester AND NEW.due_at<=(ap.end_date+1)::timestamp AT TIME ZONE ap.timezone) THEN
     RAISE EXCEPTION 'Recurring loan extension must remain within its explicit semester' USING ERRCODE='23514';
   END IF;
 ELSE
   SELECT * INTO s FROM reservation_series WHERE id=NEW.series_id;
   IF s.period_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM academic_period ap WHERE ap.id=s.period_id AND ap.is_semester
       AND NEW.start_at>=ap.start_date::timestamp AT TIME ZONE ap.timezone
       AND NEW.end_at<=(ap.end_date+1)::timestamp AT TIME ZONE ap.timezone) THEN
     RAISE EXCEPTION 'Occurrence lies outside its semester' USING ERRCODE='23514';
   END IF;
   IF TG_OP='UPDATE' AND OLD.start_at<=clock_timestamp() AND ROW(NEW.status,NEW.explanation,NEW.decided_by,NEW.decided_at)
       IS DISTINCT FROM ROW(OLD.status,OLD.explanation,OLD.decided_by,OLD.decided_at)
       AND NOT (OLD.status='Reserved' AND NEW.status='Completed' AND ROW(NEW.explanation,NEW.decided_by,NEW.decided_at)
          IS NOT DISTINCT FROM ROW(OLD.explanation,OLD.decided_by,OLD.decided_at)) THEN
     RAISE EXCEPTION 'Past occurrence decisions are immutable' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER recurring_policy_guard BEFORE INSERT OR UPDATE ON reservation_series FOR EACH ROW EXECUTE FUNCTION ras_recurring_policy_guard();
CREATE TRIGGER occurrence_policy_guard BEFORE INSERT OR UPDATE ON reservation_occurrence FOR EACH ROW EXECUTE FUNCTION ras_recurring_policy_guard();
CREATE TRIGGER extension_semester_guard BEFORE INSERT OR UPDATE ON borrow_extension FOR EACH ROW EXECUTE FUNCTION ras_recurring_policy_guard();
CREATE FUNCTION ras_priority_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (TG_OP='INSERT' AND NEW.priority<>0) OR (TG_OP='UPDATE' AND NEW.priority<>OLD.priority AND NOT EXISTS(
     SELECT 1 FROM reservation_priority_override a WHERE a.transaction_id=txid_current()
       AND a.original_priority=OLD.priority AND a.selected_priority=NEW.priority
       AND ((TG_TABLE_NAME='student_room_request' AND a.room_request_id=NEW.id)
         OR (TG_TABLE_NAME='borrow_request' AND a.borrow_request_id=NEW.id)))) THEN
   RAISE EXCEPTION 'Priority changes require an immutable reasoned audit record' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER room_priority_guard BEFORE INSERT OR UPDATE ON student_room_request FOR EACH ROW EXECUTE FUNCTION ras_priority_guard();
CREATE TRIGGER equipment_priority_guard BEFORE INSERT OR UPDATE ON borrow_request FOR EACH ROW EXECUTE FUNCTION ras_priority_guard();
CREATE FUNCTION ras_priority_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Priority override history is immutable' USING ERRCODE='23514'; END; $$;
CREATE TRIGGER priority_audit_immutable BEFORE UPDATE OR DELETE ON reservation_priority_override FOR EACH ROW EXECUTE FUNCTION ras_priority_audit_immutable();
CREATE FUNCTION ras_semester_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(NEW.start_date,NEW.end_date,NEW.timezone,NEW.is_semester) IS DISTINCT FROM ROW(OLD.start_date,OLD.end_date,OLD.timezone,OLD.is_semester)
     AND EXISTS(SELECT 1 FROM reservation_series WHERE period_id=OLD.id) THEN
   RAISE EXCEPTION 'A semester with recurring reservations cannot be redated' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER semester_reserved_dates BEFORE UPDATE ON academic_period FOR EACH ROW EXECUTE FUNCTION ras_semester_immutable();
"""


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM reservation_series) OR EXISTS(SELECT 1 FROM reservation_priority_override) OR EXISTS(SELECT 1 FROM application_state WHERE recurring_limits<>'{}'::jsonb OR reservation_priorities<>'[]'::jsonb)")):
        raise RuntimeError('Downgrade would discard recurring policy or audit history. Export and review it explicitly first.')
    op.execute('DROP TRIGGER semester_reserved_dates ON academic_period; DROP FUNCTION ras_semester_immutable()')
    op.execute('DROP TRIGGER room_priority_guard ON student_room_request; DROP TRIGGER equipment_priority_guard ON borrow_request; DROP FUNCTION ras_priority_guard()')
    op.execute('DROP TRIGGER priority_audit_immutable ON reservation_priority_override; DROP FUNCTION ras_priority_audit_immutable()')
    op.execute('DROP TRIGGER recurring_policy_guard ON reservation_series; DROP TRIGGER occurrence_policy_guard ON reservation_occurrence; DROP TRIGGER extension_semester_guard ON borrow_extension; DROP FUNCTION ras_recurring_policy_guard()')
    original=import_module('migrations.versions.0049a_recurring_reservations').SERIES_INTEGRITY
    op.execute(original.split('CREATE FUNCTION ras_room_shape')[0].replace('CREATE FUNCTION ras_series_shape','CREATE OR REPLACE FUNCTION ras_series_shape'))
    op.drop_table('reservation_priority_override')
    for table in ('student_room_request','borrow_request'):op.drop_column(table,'priority')
    for column in ('recurring_limits','reservation_priorities'):op.drop_column('application_state',column)
    op.drop_index('ix_reservation_occurrence_decided_by',table_name='reservation_occurrence')
    for column in ('explanation','decided_by','decided_at'):op.drop_column('reservation_occurrence',column)
    op.drop_constraint('ck_occurrence_outcome','reservation_occurrence',type_='check')
    op.create_check_constraint(None,'reservation_occurrence',"ordinal BETWEEN 1 AND 366 AND start_at < end_at AND status IN ('Proposed','Reserved','Completed','Cancelled')")
    op.drop_index('ix_reservation_series_period_id',table_name='reservation_series')
    op.drop_constraint('ck_series_approval_mode','reservation_series',type_='check')
    op.drop_column('reservation_series','approval_mode');op.drop_column('reservation_series','period_id')
    op.drop_column('academic_period','is_semester')
