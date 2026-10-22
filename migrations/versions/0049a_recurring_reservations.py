"""Shared dated series linked to existing room and equipment workflows."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, ExcludeConstraint

revision = '0049a'
down_revision = '0048a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('reservation_series',
        sa.Column('id',sa.BigInteger(),sa.Identity(),primary_key=True),
        sa.Column('room_request_id',sa.BigInteger(),sa.ForeignKey('student_room_request.id'),unique=True),
        sa.Column('borrow_request_id',sa.Integer(),sa.ForeignKey('borrow_request.id'),unique=True),
        sa.Column('start_date',sa.Date(),nullable=False),sa.Column('end_date',sa.Date(),nullable=False),
        sa.Column('start_minutes',sa.Integer(),nullable=False),sa.Column('duration_minutes',sa.Integer(),nullable=False),
        sa.Column('weekdays',JSONB(),nullable=False),sa.Column('timezone',sa.String(64),nullable=False),
        sa.Column('submission_key',sa.String(32),nullable=False,unique=True),sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.text('clock_timestamp()'),nullable=False),
        sa.CheckConstraint('num_nonnulls(room_request_id, borrow_request_id) = 1'),
        sa.CheckConstraint('start_date <= end_date AND end_date-start_date <= 730 AND start_minutes BETWEEN 0 AND 1439 AND duration_minutes BETWEEN 1 AND 525600'),
        sa.CheckConstraint("jsonb_typeof(weekdays) = 'array' AND jsonb_array_length(weekdays) BETWEEN 1 AND 7 AND '[1,2,3,4,5,6,7]'::jsonb @> weekdays"),
        sa.CheckConstraint("submission_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$'"))
    op.create_table('reservation_occurrence',
        sa.Column('id',sa.BigInteger(),sa.Identity(),primary_key=True),
        sa.Column('series_id',sa.BigInteger(),sa.ForeignKey('reservation_series.id'),nullable=False),
        sa.Column('ordinal',sa.Integer(),nullable=False),sa.Column('start_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('end_at',sa.DateTime(timezone=True),nullable=False),sa.Column('status',sa.String(12),nullable=False),
        sa.Column('period',TSTZRANGE(),sa.Computed("tstzrange(start_at, end_at, '[)')",persisted=True)),
        sa.UniqueConstraint('series_id','ordinal'),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 366 AND start_at < end_at AND status IN ('Proposed','Reserved','Completed','Cancelled')"),
        ExcludeConstraint(('series_id','='),('period','&&'),using='gist',name='ex_series_self_overlap'))
    op.create_index('ix_reservation_occurrence_series_id','reservation_occurrence',['series_id'])
    op.create_index('uq_equipment_outstanding_unit','equipment_reservation',['unit_id'],unique=True,
                    postgresql_where=sa.text('handed_at IS NOT NULL AND returned_at IS NULL'))
    for table in ('room_reservation','room_organizer_commitment','equipment_reservation','borrow_extension'):
        op.add_column(table,sa.Column('occurrence_id',sa.BigInteger(),sa.ForeignKey('reservation_occurrence.id')))
        if table.startswith('room_'):
            op.create_unique_constraint('uq_'+table+'_occurrence',table,['occurrence_id'])
            op.drop_constraint(table+'_pkey',table,type_='primary')
            op.create_primary_key(table+'_pkey',table,['request_id','start_at'])
        else:
            op.create_index('ix_'+table+'_occurrence_id',table,['occurrence_id'])
    op.execute('ALTER FUNCTION ras_room_shape(bigint) RENAME TO ras_room_single_shape')
    op.execute('ALTER FUNCTION ras_borrow_shape(integer) RENAME TO ras_borrow_single_shape')
    op.execute(SERIES_INTEGRITY)


SERIES_INTEGRITY = """
CREATE FUNCTION ras_series_shape(k bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE s reservation_series%ROWTYPE; r student_room_request%ROWTYPE; b borrow_request%ROWTYPE;
        n integer; expected integer; reserved integer; outstanding integer; partial boolean;
BEGIN
  SELECT * INTO s FROM reservation_series WHERE id=k;
  IF NOT FOUND THEN RETURN; END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=s.timezone)
    OR jsonb_array_length(s.weekdays)<>(SELECT count(DISTINCT value) FROM jsonb_array_elements(s.weekdays)) THEN
    RAISE EXCEPTION 'Invalid recurrence timezone or weekdays' USING ERRCODE='23514';
  END IF;
  SELECT count(*) INTO expected FROM generate_series(s.start_date::timestamp,s.end_date::timestamp,interval '1 day') d
    WHERE s.weekdays @> to_jsonb(extract(isodow FROM d)::integer);
  SELECT count(*) INTO n FROM reservation_occurrence WHERE series_id=k;
  IF n NOT BETWEEN 1 AND 366 OR n<>expected OR EXISTS(
      SELECT 1 FROM (SELECT o.*,row_number() OVER(ORDER BY start_at) position FROM reservation_occurrence o WHERE series_id=k) v
      WHERE ordinal<>position OR (start_at AT TIME ZONE s.timezone)::date NOT BETWEEN s.start_date AND s.end_date
        OR NOT (s.weekdays @> to_jsonb(extract(isodow FROM start_at AT TIME ZONE s.timezone)::integer))
        OR extract(hour FROM start_at AT TIME ZONE s.timezone)*60+extract(minute FROM start_at AT TIME ZONE s.timezone)<>s.start_minutes
        OR extract(second FROM start_at)<>0 OR end_at<>start_at+s.duration_minutes*interval '1 minute') THEN
    RAISE EXCEPTION 'Series must retain its complete ordered dated expansion' USING ERRCODE='23514';
  END IF;
  IF s.room_request_id IS NOT NULL THEN
    SELECT * INTO r FROM student_room_request WHERE id=s.room_request_id;
    IF r.status<>'Confirmed' THEN
      PERFORM ras_room_single_shape(r.id);
      IF EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status NOT IN ('Proposed','Cancelled')) THEN
        RAISE EXCEPTION 'Unapproved room series cannot hold confirmed occurrences' USING ERRCODE='23514';
      END IF;
      RETURN;
    END IF;
    IF r.approved_revision IS DISTINCT FROM r.revision OR r.approved_by IS DISTINCT FROM r.approver_id
      OR r.attendee_count<1+(SELECT count(*) FROM room_invitation WHERE request_id=r.id)
      OR NOT EXISTS(SELECT 1 FROM university_user u JOIN role p ON p.id=u.primary_role_id WHERE u.id=r.organizer_id AND p.name='Student')
      OR EXISTS(SELECT 1 FROM room_invitation i JOIN university_user u ON u.id=i.user_id JOIN role p ON p.id=u.primary_role_id
          WHERE i.request_id=r.id AND (i.revision<>r.revision OR i.user_id=r.organizer_id OR p.name NOT IN ('Instructor','Student') OR (p.name='Student' AND i.status<>'Accepted')))
      OR EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status NOT IN ('Reserved','Cancelled')) THEN
      RAISE EXCEPTION 'Room series approval or participation is inconsistent' USING ERRCODE='23514';
    END IF;
    SELECT count(*) INTO reserved FROM reservation_occurrence WHERE series_id=k AND status='Reserved';
    IF reserved=0 OR reserved<>(SELECT count(*) FROM room_reservation WHERE request_id=r.id)
      OR reserved<>(SELECT count(*) FROM room_organizer_commitment WHERE request_id=r.id)
      OR EXISTS(SELECT 1 FROM reservation_occurrence o WHERE o.series_id=k AND o.status='Reserved' AND (
          NOT EXISTS(SELECT 1 FROM room_reservation x WHERE x.occurrence_id=o.id AND x.request_id=r.id AND x.resource_id=r.resource_id AND x.start_at=o.start_at AND x.end_at=o.end_at)
          OR NOT EXISTS(SELECT 1 FROM room_organizer_commitment x WHERE x.occurrence_id=o.id AND x.request_id=r.id AND x.user_id=r.organizer_id AND x.start_at=o.start_at AND x.end_at=o.end_at))) THEN
      RAISE EXCEPTION 'Every approved room occurrence needs exact room and organizer reservations' USING ERRCODE='23514';
    END IF;
  ELSE
    SELECT * INTO b FROM borrow_request WHERE id=s.borrow_request_id;
    IF NOT EXISTS(SELECT 1 FROM university_user u JOIN role p ON p.id=u.primary_role_id WHERE u.id=b.borrower_id AND p.name='Student')
      OR (SELECT count(*) FROM borrow_item WHERE request_id=b.id) NOT BETWEEN 1 AND 50 THEN
      RAISE EXCEPTION 'Equipment series requires a student and complete items' USING ERRCODE='23514';
    END IF;
    IF EXISTS(SELECT 1 FROM equipment_reservation x JOIN borrow_item i ON i.id=x.item_id
      LEFT JOIN reservation_occurrence o ON o.id=x.occurrence_id WHERE i.request_id=b.id AND (
        o.id IS NULL OR o.series_id<>k OR x.start_at<>o.start_at OR x.due_at>greatest(o.end_at,
          (SELECT max(e.due_at) FROM borrow_extension e WHERE e.occurrence_id=o.id AND e.request_id=b.id AND e.status='Approved'))
        OR (o.status='Cancelled' AND (NOT x.released OR x.handed_at IS NOT NULL))
        OR (o.status='Completed' AND x.returned_at IS NULL) OR o.status='Proposed'
        OR (o.status='Reserved' AND x.released AND x.handed_at IS NULL)))
      OR EXISTS(SELECT 1 FROM reservation_occurrence o CROSS JOIN borrow_item i
        WHERE o.series_id=k AND i.request_id=b.id AND o.status IN ('Reserved','Completed') AND i.quantity<>(
          SELECT count(*) FROM equipment_reservation x WHERE x.item_id=i.id AND x.occurrence_id=o.id)) THEN
      RAISE EXCEPTION 'Every equipment occurrence must fulfill exact quantities and physical records' USING ERRCODE='23514';
    END IF;
    SELECT count(*) FILTER(WHERE x.handed_at IS NOT NULL AND x.returned_at IS NULL),
           coalesce(bool_or(x.handed_at IS NOT NULL AND x.returned_at IS NOT NULL AND o.status='Reserved'),false)
      INTO outstanding,partial FROM equipment_reservation x JOIN borrow_item i ON i.id=x.item_id
      JOIN reservation_occurrence o ON o.id=x.occurrence_id WHERE i.request_id=b.id;
    SELECT count(*) INTO reserved FROM reservation_occurrence WHERE series_id=k AND status='Reserved';
    IF (b.status IN ('Pending Approval','Rejected') AND EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status NOT IN ('Proposed','Cancelled')))
      OR (b.status='Cancelled' AND EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status<>'Cancelled'))
      OR (b.status IN ('Approved','Borrowed','Partially Returned','Returned') AND EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status='Proposed'))
      OR (b.status='Approved' AND (outstanding<>0 OR reserved=0))
      OR (b.status='Borrowed' AND (outstanding=0 OR partial))
      OR (b.status='Partially Returned' AND (outstanding=0 OR NOT partial))
      OR (b.status='Returned' AND (outstanding<>0 OR reserved<>0 OR NOT EXISTS(SELECT 1 FROM reservation_occurrence WHERE series_id=k AND status='Completed'))) THEN
      RAISE EXCEPTION 'Equipment series state disagrees with its occurrence lifecycle' USING ERRCODE='23514';
    END IF;
  END IF;
END; $$;
CREATE FUNCTION ras_room_shape(k bigint) RETURNS void LANGUAGE plpgsql AS $$
DECLARE s bigint;
BEGIN
 SELECT id INTO s FROM reservation_series WHERE room_request_id=k;
 IF FOUND THEN PERFORM ras_series_shape(s); ELSE PERFORM ras_room_single_shape(k); END IF;
END; $$;
CREATE FUNCTION ras_borrow_shape(k integer) RETURNS void LANGUAGE plpgsql AS $$
DECLARE s bigint;
BEGIN
 SELECT id INTO s FROM reservation_series WHERE borrow_request_id=k;
 IF FOUND THEN PERFORM ras_series_shape(s); ELSE PERFORM ras_borrow_single_shape(k); END IF;
END; $$;
CREATE FUNCTION ras_series_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='reservation_series' THEN
   IF TG_OP<>'INSERT' THEN PERFORM ras_series_shape(OLD.id); END IF;
   IF TG_OP<>'DELETE' THEN PERFORM ras_series_shape(NEW.id); END IF;
 ELSE
   IF TG_OP<>'INSERT' THEN PERFORM ras_series_shape(OLD.series_id); END IF;
   IF TG_OP<>'DELETE' THEN PERFORM ras_series_shape(NEW.series_id); END IF;
 END IF;
 RETURN NULL;
END; $$;
CREATE FUNCTION ras_series_lock() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE s reservation_series%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='reservation_series' THEN
   IF TG_OP<>'INSERT' THEN
     IF TG_OP='DELETE' OR ROW(NEW.room_request_id,NEW.borrow_request_id,NEW.start_date,NEW.end_date,NEW.start_minutes,NEW.duration_minutes,NEW.weekdays,NEW.timezone,NEW.submission_key,NEW.fingerprint)
       IS DISTINCT FROM ROW(OLD.room_request_id,OLD.borrow_request_id,OLD.start_date,OLD.end_date,OLD.start_minutes,OLD.duration_minutes,OLD.weekdays,OLD.timezone,OLD.submission_key,OLD.fingerprint) THEN
       RAISE EXCEPTION 'Series identity and proposed calendar are immutable; cancel future occurrences and submit a fresh proposal' USING ERRCODE='23514';
     END IF;
   END IF;
   s:=NEW;
 ELSE
   IF TG_OP<>'INSERT' THEN
     IF TG_OP='DELETE' OR ROW(NEW.series_id,NEW.ordinal,NEW.start_at,NEW.end_at) IS DISTINCT FROM ROW(OLD.series_id,OLD.ordinal,OLD.start_at,OLD.end_at) THEN
       RAISE EXCEPTION 'Occurrence identity and dates are historical records' USING ERRCODE='23514';
     END IF;
   END IF;
   SELECT * INTO s FROM reservation_series WHERE id=NEW.series_id;
 END IF;
 IF s.room_request_id IS NOT NULL THEN UPDATE student_room_request SET revision=revision WHERE id=s.room_request_id;
 ELSE UPDATE borrow_request SET status=status WHERE id=s.borrow_request_id; END IF;
 RETURN NEW;
END; $$;
CREATE TRIGGER reservation_series_lock BEFORE INSERT OR UPDATE OR DELETE ON reservation_series FOR EACH ROW EXECUTE FUNCTION ras_series_lock();
CREATE TRIGGER reservation_occurrence_lock BEFORE INSERT OR UPDATE OR DELETE ON reservation_occurrence FOR EACH ROW EXECUTE FUNCTION ras_series_lock();
CREATE CONSTRAINT TRIGGER reservation_series_shape AFTER INSERT OR UPDATE OR DELETE ON reservation_series DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ras_series_changed();
CREATE CONSTRAINT TRIGGER reservation_occurrence_shape AFTER INSERT OR UPDATE OR DELETE ON reservation_occurrence DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ras_series_changed();
"""


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS(SELECT 1 FROM reservation_series)')):
        raise RuntimeError('Downgrade would discard recurring history. Export and review it explicitly first.')
    for table in ('reservation_occurrence','reservation_series'):
        op.execute(f'DROP TRIGGER {table}_shape ON {table}; DROP TRIGGER {table}_lock ON {table}')
    op.execute('DROP FUNCTION ras_series_changed(); DROP FUNCTION ras_series_lock(); DROP FUNCTION ras_series_shape(bigint)')
    op.execute('DROP FUNCTION ras_room_shape(bigint); DROP FUNCTION ras_borrow_shape(integer)')
    op.execute('ALTER FUNCTION ras_room_single_shape(bigint) RENAME TO ras_room_shape')
    op.execute('ALTER FUNCTION ras_borrow_single_shape(integer) RENAME TO ras_borrow_shape')
    op.drop_index('uq_equipment_outstanding_unit',table_name='equipment_reservation')
    for table in ('room_reservation','room_organizer_commitment','equipment_reservation','borrow_extension'):
        if table.startswith('room_'):
            op.drop_constraint('uq_'+table+'_occurrence',table,type_='unique')
            op.drop_constraint(table+'_pkey',table,type_='primary')
            op.create_primary_key(table+'_pkey',table,['request_id'])
        else:op.drop_index('ix_'+table+'_occurrence_id',table_name=table)
        op.drop_column(table,'occurrence_id')
    op.drop_table('reservation_occurrence');op.drop_table('reservation_series')
