"""Deferred aggregate checks: professor revisions and confirmed reservations agree."""

from alembic import op

revision = "0042b"
down_revision = "0042a"
branch_labels = None
depends_on = None

TABLES = ("appointment", "appointment_professor", "appointment_invitation", "appointment_commitment")


def upgrade():
    op.execute("""
    CREATE FUNCTION ras_check_appointment_shape(appointment_key bigint) RETURNS void
    LANGUAGE plpgsql AS $$
    DECLARE record appointment%ROWTYPE; professors bigint; reservations bigint;
    BEGIN
        SELECT * INTO record FROM appointment WHERE id = appointment_key;
        IF NOT FOUND THEN RETURN; END IF;
        SELECT count(*) INTO professors FROM appointment_professor WHERE appointment_id = appointment_key;
        IF professors < 1 OR NOT EXISTS (SELECT 1 FROM university_user u JOIN role r ON r.id = u.primary_role_id
                WHERE u.id = record.organizer_id AND r.name = 'Student')
           OR EXISTS (SELECT 1 FROM appointment_professor p JOIN university_user u ON u.id = p.user_id JOIN role r ON r.id = u.primary_role_id
                WHERE p.appointment_id = appointment_key AND (r.name <> 'Instructor' OR p.revision <> record.revision OR p.user_id = record.organizer_id))
           OR EXISTS (SELECT 1 FROM appointment_invitation i JOIN university_user u ON u.id = i.user_id JOIN role r ON r.id = u.primary_role_id
                WHERE i.appointment_id = appointment_key AND (r.name <> 'Student' OR i.user_id = record.organizer_id)) THEN
            RAISE EXCEPTION 'Appointment % has inconsistent participants or revisions', appointment_key
                USING ERRCODE = '23514', CONSTRAINT = 'appointment_aggregate_complete';
        END IF;
        SELECT count(*) INTO reservations FROM appointment_commitment WHERE appointment_id = appointment_key;
        IF record.status = 'Confirmed' THEN
            IF reservations <> professors + 1
               OR EXISTS (SELECT 1 FROM appointment_professor WHERE appointment_id = appointment_key AND decision <> 'Approved')
               OR NOT EXISTS (SELECT 1 FROM appointment_commitment WHERE appointment_id = appointment_key AND user_id = record.organizer_id)
               OR EXISTS (SELECT 1 FROM appointment_professor p WHERE appointment_id = appointment_key AND NOT EXISTS
                    (SELECT 1 FROM appointment_commitment c WHERE c.appointment_id = appointment_key AND c.user_id = p.user_id))
               OR EXISTS (SELECT 1 FROM appointment_commitment WHERE appointment_id = appointment_key
                    AND (start_at <> record.start_at OR end_at <> record.end_at)) THEN
                RAISE EXCEPTION 'Confirmed appointment % lacks exact unanimously approved commitments', appointment_key
                    USING ERRCODE = '23514', CONSTRAINT = 'appointment_aggregate_complete';
            END IF;
        ELSIF reservations <> 0 THEN
            RAISE EXCEPTION 'Unconfirmed appointment % must not reserve time', appointment_key
                USING ERRCODE = '23514', CONSTRAINT = 'appointment_aggregate_complete';
        END IF;
        IF (record.status = 'Declined' AND NOT EXISTS (SELECT 1 FROM appointment_professor WHERE appointment_id = appointment_key AND decision = 'Declined'))
           OR (record.status = 'Pending Approval' AND EXISTS (SELECT 1 FROM appointment_professor WHERE appointment_id = appointment_key AND decision = 'Declined')) THEN
            RAISE EXCEPTION 'Appointment % state disagrees with professor decisions', appointment_key
                USING ERRCODE = '23514', CONSTRAINT = 'appointment_aggregate_complete';
        END IF;
    END; $$;
    CREATE FUNCTION ras_appointment_shape_changed() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_TABLE_NAME = 'appointment' THEN
            IF TG_OP <> 'INSERT' THEN PERFORM ras_check_appointment_shape(OLD.id); END IF;
            IF TG_OP <> 'DELETE' THEN PERFORM ras_check_appointment_shape(NEW.id); END IF;
        ELSE
            IF TG_OP <> 'INSERT' THEN PERFORM ras_check_appointment_shape(OLD.appointment_id); END IF;
            IF TG_OP <> 'DELETE' THEN PERFORM ras_check_appointment_shape(NEW.appointment_id); END IF;
        END IF;
        RETURN NULL;
    END; $$;
    CREATE FUNCTION ras_lock_appointment_shape() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE keys bigint[] := '{}'; appointment_key bigint;
    BEGIN
        IF TG_OP <> 'INSERT' THEN keys := array_append(keys, OLD.appointment_id); END IF;
        IF TG_OP <> 'DELETE' THEN keys := array_append(keys, NEW.appointment_id); END IF;
        FOR appointment_key IN SELECT DISTINCT value FROM unnest(keys) AS ids(value) ORDER BY value LOOP
            UPDATE appointment SET revision = revision WHERE id = appointment_key;
        END LOOP;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END; $$;
    """)
    op.execute("SELECT ras_check_appointment_shape(id) FROM appointment")
    for table in TABLES:
        op.execute(f"CREATE CONSTRAINT TRIGGER {table}_aggregate_complete AFTER INSERT OR UPDATE OR DELETE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ras_appointment_shape_changed()")
        if table != "appointment":
            op.execute(f"CREATE TRIGGER {table}_shape_lock BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION ras_lock_appointment_shape()")


def downgrade():
    for table in reversed(TABLES):
        if table != "appointment":
            op.execute(f"DROP TRIGGER {table}_shape_lock ON {table}")
        op.execute(f"DROP TRIGGER {table}_aggregate_complete ON {table}")
    op.execute("DROP FUNCTION ras_lock_appointment_shape()")
    op.execute("DROP FUNCTION ras_appointment_shape_changed()")
    op.execute("DROP FUNCTION ras_check_appointment_shape(bigint)")
