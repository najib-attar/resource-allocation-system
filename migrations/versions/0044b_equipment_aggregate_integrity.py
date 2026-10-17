"""Commit-time inventory aggregate integrity; matching remains in the engine."""
from alembic import op

revision = '0044b'
down_revision = '0044a'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE FUNCTION ras_equipment_faculty() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM organization_unit WHERE id=NEW.faculty_id AND unit_type='Faculty') THEN
        RAISE EXCEPTION 'Equipment requires a configured faculty' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER equipment_type_faculty BEFORE INSERT OR UPDATE ON equipment_type
      FOR EACH ROW EXECUTE FUNCTION ras_equipment_faculty();
    CREATE TRIGGER equipment_custodian_faculty BEFORE INSERT OR UPDATE ON equipment_custodian
      FOR EACH ROW EXECUTE FUNCTION ras_equipment_faculty();
    CREATE TRIGGER borrow_request_faculty BEFORE INSERT OR UPDATE ON borrow_request
      FOR EACH ROW EXECUTE FUNCTION ras_equipment_faculty();

    CREATE FUNCTION ras_borrow_shape(k integer) RETURNS void LANGUAGE plpgsql AS $$
    DECLARE r borrow_request%ROWTYPE; n integer; handed integer; returned integer;
    BEGIN
      SELECT * INTO r FROM borrow_request WHERE id=k;
      IF NOT FOUND THEN RETURN; END IF;
      IF NOT EXISTS (SELECT 1 FROM university_user u JOIN role p ON p.id=u.primary_role_id
                      WHERE u.id=r.borrower_id AND p.name='Student')
        OR (SELECT count(*) FROM borrow_item WHERE request_id=k) NOT BETWEEN 1 AND 50 THEN
        RAISE EXCEPTION 'Borrowing requires a student and complete request items' USING ERRCODE='23514';
      END IF;
      IF r.status IN ('Pending Approval','Rejected','Cancelled') THEN
        IF EXISTS (SELECT 1 FROM equipment_reservation b JOIN borrow_item i ON i.id=b.item_id
                   WHERE i.request_id=k AND NOT b.released) THEN
          RAISE EXCEPTION 'Unapproved requests cannot reserve units' USING ERRCODE='23514';
        END IF;
        RETURN;
      END IF;
      IF EXISTS (SELECT 1 FROM borrow_item i WHERE i.request_id=k AND i.quantity<>(
          SELECT count(*) FROM equipment_reservation b WHERE b.item_id=i.id))
        OR EXISTS (SELECT 1 FROM equipment_reservation b JOIN borrow_item i ON i.id=b.item_id
                   WHERE i.request_id=k AND (b.start_at<>r.start_at OR b.due_at>r.due_at)) THEN
        RAISE EXCEPTION 'Reserved units must fulfill every requested quantity and interval' USING ERRCODE='23514';
      END IF;
      SELECT count(*),count(b.handed_at),count(b.returned_at) INTO n,handed,returned
        FROM equipment_reservation b JOIN borrow_item i ON i.id=b.item_id WHERE i.request_id=k;
      IF (r.status='Approved' AND (handed<>0 OR EXISTS(SELECT 1 FROM equipment_reservation b
            JOIN borrow_item i ON i.id=b.item_id WHERE i.request_id=k AND b.released)))
        OR (r.status='Borrowed' AND (handed<>n OR returned<>0))
        OR (r.status='Partially Returned' AND (handed<>n OR returned NOT BETWEEN 1 AND n-1))
        OR (r.status='Returned' AND returned<>n) THEN
        RAISE EXCEPTION 'Loan state disagrees with physical handover/return records' USING ERRCODE='23514';
      END IF;
    END; $$;
    CREATE FUNCTION ras_borrow_check() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE k integer;
    BEGIN
      IF TG_TABLE_NAME='borrow_request' THEN
        PERFORM ras_borrow_shape(CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END);
      ELSIF TG_TABLE_NAME='borrow_item' THEN
        IF TG_OP<>'INSERT' THEN PERFORM ras_borrow_shape(OLD.request_id); END IF;
        IF TG_OP<>'DELETE' THEN PERFORM ras_borrow_shape(NEW.request_id); END IF;
      ELSE
        IF TG_OP<>'INSERT' THEN
          SELECT request_id INTO k FROM borrow_item WHERE id=OLD.item_id;
          PERFORM ras_borrow_shape(k);
        END IF;
        IF TG_OP<>'DELETE' THEN
          SELECT request_id INTO k FROM borrow_item WHERE id=NEW.item_id;
          PERFORM ras_borrow_shape(k);
        END IF;
      END IF;
      RETURN NULL;
    END; $$;
    CREATE CONSTRAINT TRIGGER borrow_request_shape AFTER INSERT OR UPDATE OR DELETE ON borrow_request
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ras_borrow_check();
    CREATE CONSTRAINT TRIGGER borrow_item_shape AFTER INSERT OR UPDATE OR DELETE ON borrow_item
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ras_borrow_check();
    CREATE CONSTRAINT TRIGGER equipment_reservation_shape AFTER INSERT OR UPDATE OR DELETE ON equipment_reservation
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ras_borrow_check();
    """)


def downgrade():
    for table in ('borrow_request', 'borrow_item', 'equipment_reservation'):
        op.execute('DROP TRIGGER '+table+'_shape ON '+table)
    op.execute('DROP FUNCTION ras_borrow_check(); DROP FUNCTION ras_borrow_shape(integer)')
    for table in ('equipment_type', 'equipment_custodian', 'borrow_request'):
        op.execute('DROP TRIGGER '+table+'_faculty ON '+table)
    op.execute('DROP FUNCTION ras_equipment_faculty()')
