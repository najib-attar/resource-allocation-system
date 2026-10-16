"""Exact confirmed room aggregates and cross-service person overlap protection."""

from alembic import op

revision = '0043b'
down_revision = '0043a'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION ras_room_faculty() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM organization_unit WHERE id=NEW.faculty_id AND unit_type='Faculty') THEN
            RAISE EXCEPTION 'Room ownership and approval require a faculty' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END; $$;
    CREATE TRIGGER room_policy_faculty BEFORE INSERT OR UPDATE ON room_policy FOR EACH ROW EXECUTE FUNCTION ras_room_faculty();
    CREATE TRIGGER faculty_room_approver_faculty BEFORE INSERT OR UPDATE ON faculty_room_approver FOR EACH ROW EXECUTE FUNCTION ras_room_faculty();

    CREATE FUNCTION ras_room_shape(k bigint) RETURNS void LANGUAGE plpgsql AS $$
    DECLARE r student_room_request%ROWTYPE; nr bigint; nc bigint;
    BEGIN
        SELECT * INTO r FROM student_room_request WHERE id=k;
        IF NOT FOUND THEN RETURN; END IF;
        IF NOT EXISTS (SELECT 1 FROM university_user u JOIN role p ON p.id=u.primary_role_id WHERE u.id=r.organizer_id AND p.name='Student')
          OR NOT EXISTS (SELECT 1 FROM organization_unit WHERE id=r.faculty_id AND unit_type='Faculty')
          OR EXISTS (SELECT 1 FROM room_invitation i JOIN university_user u ON u.id=i.user_id JOIN role p ON p.id=u.primary_role_id
             WHERE i.request_id=k AND (i.revision<>r.revision OR p.name<>'Instructor' OR i.user_id=r.organizer_id)) THEN
            RAISE EXCEPTION 'Room request % has inconsistent participants',k USING ERRCODE='23514';
        END IF;
        SELECT count(*) INTO nr FROM room_reservation WHERE request_id=k;
        SELECT count(*) INTO nc FROM room_organizer_commitment WHERE request_id=k;
        IF r.status='Confirmed' THEN
            IF nr<>1 OR nc<>1 OR r.approved_revision IS DISTINCT FROM r.revision OR r.approved_by IS DISTINCT FROM r.approver_id
              OR EXISTS (SELECT 1 FROM room_reservation WHERE request_id=k AND (resource_id<>r.resource_id OR start_at<>r.start_at OR end_at<>r.end_at))
              OR EXISTS (SELECT 1 FROM room_organizer_commitment WHERE request_id=k AND (user_id<>r.organizer_id OR start_at<>r.start_at OR end_at<>r.end_at)) THEN
                RAISE EXCEPTION 'Confirmed room request % lacks exact approved reservations',k USING ERRCODE='23514';
            END IF;
        ELSIF nr<>0 OR nc<>0 THEN
            RAISE EXCEPTION 'Unconfirmed room request % cannot reserve time',k USING ERRCODE='23514';
        END IF;
    END; $$;
    CREATE FUNCTION ras_room_shape_changed() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_TABLE_NAME='student_room_request' THEN
            IF TG_OP<>'INSERT' THEN PERFORM ras_room_shape(OLD.id); END IF;
            IF TG_OP<>'DELETE' THEN PERFORM ras_room_shape(NEW.id); END IF;
        ELSE
            IF TG_OP<>'INSERT' THEN PERFORM ras_room_shape(OLD.request_id); END IF;
            IF TG_OP<>'DELETE' THEN PERFORM ras_room_shape(NEW.request_id); END IF;
        END IF;
        RETURN NULL;
    END; $$;
    CREATE FUNCTION ras_lock_room_shape() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE keys bigint[] := '{}'; k bigint;
    BEGIN
        IF TG_OP<>'INSERT' THEN keys:=array_append(keys,OLD.request_id); END IF;
        IF TG_OP<>'DELETE' THEN keys:=array_append(keys,NEW.request_id); END IF;
        FOR k IN SELECT DISTINCT value FROM unnest(keys) AS ids(value) ORDER BY value LOOP
            UPDATE student_room_request SET revision=revision WHERE id=k;
        END LOOP;
        IF TG_OP='DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END; $$;

    CREATE FUNCTION ras_person_calendar_overlap() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        -- Both services serialize by identity even when a caller uses direct SQL.
        UPDATE university_user SET id=id WHERE id=NEW.user_id;
        IF TG_TABLE_NAME='appointment_commitment' THEN
            IF EXISTS (SELECT 1 FROM room_organizer_commitment WHERE user_id=NEW.user_id AND start_at<NEW.end_at AND end_at>NEW.start_at) THEN
                RAISE EXCEPTION 'Person already reserved by room request' USING ERRCODE='23P01';
            END IF;
        ELSE
            IF EXISTS (SELECT 1 FROM appointment_commitment WHERE user_id=NEW.user_id AND start_at<NEW.end_at AND end_at>NEW.start_at) THEN
                RAISE EXCEPTION 'Person already reserved by appointment' USING ERRCODE='23P01';
            END IF;
        END IF;
        RETURN NEW;
    END; $$;
    CREATE TRIGGER appointment_room_person_overlap BEFORE INSERT OR UPDATE ON appointment_commitment FOR EACH ROW EXECUTE FUNCTION ras_person_calendar_overlap();
    CREATE TRIGGER room_appointment_person_overlap BEFORE INSERT OR UPDATE ON room_organizer_commitment FOR EACH ROW EXECUTE FUNCTION ras_person_calendar_overlap();
    """)
    for table in ('student_room_request', 'room_invitation', 'room_reservation', 'room_organizer_commitment'):
        op.execute(f"CREATE CONSTRAINT TRIGGER {table}_complete AFTER INSERT OR UPDATE OR DELETE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ras_room_shape_changed()")
        if table != 'student_room_request':
            op.execute(f"CREATE TRIGGER {table}_shape_lock BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION ras_lock_room_shape()")


def downgrade():
    for table in ('room_organizer_commitment', 'room_reservation', 'room_invitation', 'student_room_request'):
        if table != 'student_room_request':
            op.execute(f'DROP TRIGGER {table}_shape_lock ON {table}')
        op.execute(f'DROP TRIGGER {table}_complete ON {table}')
    op.execute('DROP TRIGGER appointment_room_person_overlap ON appointment_commitment')
    op.execute('DROP TRIGGER room_appointment_person_overlap ON room_organizer_commitment')
    op.execute('DROP FUNCTION ras_person_calendar_overlap()')
    op.execute('DROP FUNCTION ras_lock_room_shape()')
    op.execute('DROP FUNCTION ras_room_shape_changed()')
    op.execute('DROP FUNCTION ras_room_shape(bigint)')
    op.execute('DROP TRIGGER faculty_room_approver_faculty ON faculty_room_approver')
    op.execute('DROP TRIGGER room_policy_faculty ON room_policy')
    op.execute('DROP FUNCTION ras_room_faculty()')
