"""Deferred subtype completeness checks; preserve existing records or fail upgrade."""

from alembic import op

revision = "0041d"
down_revision = "0041c"
branch_labels = None
depends_on = None

TABLES = ("resource_request", "request_slot", "exam_details", "request_participant")


def upgrade():
    op.execute("""
    CREATE FUNCTION ras_check_request_shape(request_key integer) RETURNS void
    LANGUAGE plpgsql AS $$
    DECLARE request_type text; slot_count bigint; has_exam boolean; has_participants boolean;
    BEGIN
        SELECT type INTO request_type FROM resource_request WHERE id = request_key;
        IF NOT FOUND THEN RETURN; END IF;
        SELECT count(*) INTO slot_count FROM request_slot WHERE request_id = request_key;
        SELECT EXISTS (SELECT 1 FROM exam_details WHERE request_id = request_key) INTO has_exam;
        SELECT EXISTS (SELECT 1 FROM request_participant WHERE request_id = request_key) INTO has_participants;
        IF slot_count < 1 OR slot_count > 10000
           OR (request_type <> 'Recurring' AND slot_count <> 1)
           OR ((request_type = 'Exam') <> has_exam)
           OR (request_type <> 'CommitteeMeeting' AND has_participants) THEN
            RAISE EXCEPTION 'Request % has inconsistent subtype records', request_key
                USING ERRCODE = '23514', CONSTRAINT = 'request_subtype_complete';
        END IF;
    END;
    $$;
    """)
    # Validate old records transactionally, without deleting or guessing repairs.
    op.execute("SELECT ras_check_request_shape(id) FROM resource_request")
    op.execute("""
    CREATE FUNCTION ras_lock_request_shape() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE keys integer[] := '{}'; request_key integer;
    BEGIN
        IF TG_OP <> 'INSERT' THEN keys := array_append(keys, OLD.request_id); END IF;
        IF TG_OP <> 'DELETE' THEN keys := array_append(keys, NEW.request_id); END IF;
        FOR request_key IN SELECT DISTINCT value FROM unnest(keys) AS ids(value) ORDER BY value LOOP
            -- A row-version write prevents child-table write skew, including at repeatable read.
            UPDATE resource_request SET revision = revision WHERE id = request_key;
        END LOOP;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END;
    $$;
    """)
    op.execute("""
    CREATE FUNCTION ras_request_shape_changed() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_TABLE_NAME = 'resource_request' THEN
            IF TG_OP <> 'INSERT' THEN PERFORM ras_check_request_shape(OLD.id); END IF;
            IF TG_OP <> 'DELETE' THEN PERFORM ras_check_request_shape(NEW.id); END IF;
        ELSE
            IF TG_OP <> 'INSERT' THEN PERFORM ras_check_request_shape(OLD.request_id); END IF;
            IF TG_OP <> 'DELETE' THEN PERFORM ras_check_request_shape(NEW.request_id); END IF;
        END IF;
        RETURN NULL;
    END;
    $$;
    """)
    for table in TABLES:
        op.execute(f"CREATE CONSTRAINT TRIGGER {table}_subtype_complete AFTER INSERT OR UPDATE OR DELETE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ras_request_shape_changed()")
        if table != "resource_request":
            op.execute(f"CREATE TRIGGER {table}_shape_lock BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION ras_lock_request_shape()")


def downgrade():
    for table in reversed(TABLES):
        if table != "resource_request":
            op.execute(f"DROP TRIGGER {table}_shape_lock ON {table}")
        op.execute(f"DROP TRIGGER {table}_subtype_complete ON {table}")
    op.execute("DROP FUNCTION ras_request_shape_changed()")
    op.execute("DROP FUNCTION ras_lock_request_shape()")
    op.execute("DROP FUNCTION ras_check_request_shape(integer)")
