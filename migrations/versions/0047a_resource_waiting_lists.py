"""One shared waiting list linked to existing room and equipment requests."""
from alembic import op
import sqlalchemy as sa

revision = '0047a'
down_revision = '0045a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('application_state', sa.Column('waiting_notice_minutes', sa.Integer(), nullable=True))
    op.create_check_constraint('ck_waiting_notice', 'application_state', 'waiting_notice_minutes > 0')
    op.create_table('waiting_list_entry',
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column('room_request_id', sa.BigInteger(), sa.ForeignKey('student_room_request.id'), unique=True),
        sa.Column('borrow_request_id', sa.Integer(), sa.ForeignKey('borrow_request.id'), unique=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('university_user.id'), nullable=False),
        sa.Column('faculty_id', sa.Integer(), sa.ForeignKey('organization_unit.id'), nullable=False),
        sa.Column('submission_key', sa.String(32), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('queue_key', sa.String(64), nullable=False),
        sa.Column('policy_version', sa.String(100), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.Column('notice_minutes', sa.Integer()),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('approved_by', sa.Integer(), sa.ForeignKey('login_account.user_id')),
        sa.Column('approved_at', sa.DateTime(timezone=True)),
        sa.Column('top_three_notified', sa.Boolean(), nullable=False),
        sa.Column('first_notified', sa.Boolean(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.UniqueConstraint('owner_id', 'submission_key'),
        sa.CheckConstraint('num_nonnulls(room_request_id, borrow_request_id) = 1', name='ck_waiting_parent'),
        sa.CheckConstraint("status IN ('Pending Review','Preapproved','Assigned','Rejected','Cancelled','Expired','Ineligible')", name='ck_waiting_status'),
        sa.CheckConstraint("submission_key ~ '^[0-9a-f]{32}$' AND fingerprint ~ '^[0-9a-f]{64}$' AND queue_key ~ '^[0-9a-f]{64}$'", name='ck_waiting_keys'),
        sa.CheckConstraint("length(policy_version) > 0 AND (notice_minutes IS NULL OR notice_minutes > 0)", name='ck_waiting_consent'),
        sa.CheckConstraint("status NOT IN ('Preapproved','Assigned') OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)", name='ck_waiting_approval'))
    op.create_index('ix_waiting_list_entry_owner_id', 'waiting_list_entry', ['owner_id'])
    op.create_index('ix_waiting_list_entry_approved_by', 'waiting_list_entry', ['approved_by'])
    op.create_index('ix_waiting_faculty_status_id', 'waiting_list_entry', ['faculty_id', 'status', 'id'])
    op.create_index('ix_waiting_queue_status_id', 'waiting_list_entry', ['queue_key', 'status', 'id'])
    op.execute("""
    CREATE FUNCTION ras_waiting_shape(k bigint) RETURNS void LANGUAGE plpgsql AS $$
    DECLARE w waiting_list_entry%ROWTYPE; owner integer; faculty integer; parent_status text;
    BEGIN
      SELECT * INTO w FROM waiting_list_entry WHERE id=k;
      IF NOT FOUND THEN RETURN; END IF;
      IF w.room_request_id IS NOT NULL THEN
        SELECT organizer_id,faculty_id,status INTO owner,faculty,parent_status FROM student_room_request WHERE id=w.room_request_id;
        IF w.status IN ('Pending Review','Preapproved') AND parent_status<>'Pending Faculty Approval' THEN
          RAISE EXCEPTION 'Active room queue must remain unreserved' USING ERRCODE='23514';
        END IF;
        IF w.status='Assigned' AND parent_status NOT IN ('Confirmed','Cancelled') THEN
          RAISE EXCEPTION 'Assigned room queue requires a confirmed reservation' USING ERRCODE='23514';
        END IF;
      ELSE
        SELECT borrower_id,faculty_id,status INTO owner,faculty,parent_status FROM borrow_request WHERE id=w.borrow_request_id;
        IF w.status IN ('Pending Review','Preapproved') AND parent_status<>'Pending Approval' THEN
          RAISE EXCEPTION 'Active equipment queue must remain unreserved' USING ERRCODE='23514';
        END IF;
        IF w.status='Assigned' AND parent_status NOT IN ('Approved','Borrowed','Partially Returned','Returned','Cancelled') THEN
          RAISE EXCEPTION 'Assigned equipment queue requires a reserved loan' USING ERRCODE='23514';
        END IF;
      END IF;
      IF owner IS DISTINCT FROM w.owner_id OR faculty IS DISTINCT FROM w.faculty_id THEN
        RAISE EXCEPTION 'Queue ownership must match its original request' USING ERRCODE='23514';
      END IF;
    END; $$;
    CREATE FUNCTION ras_waiting_changed() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE k bigint;
    BEGIN
      IF TG_TABLE_NAME='waiting_list_entry' THEN
        PERFORM ras_waiting_shape(NEW.id);
      ELSIF TG_TABLE_NAME='student_room_request' THEN
        FOR k IN SELECT id FROM waiting_list_entry WHERE room_request_id=NEW.id LOOP PERFORM ras_waiting_shape(k); END LOOP;
      ELSE
        FOR k IN SELECT id FROM waiting_list_entry WHERE borrow_request_id=NEW.id LOOP PERFORM ras_waiting_shape(k); END LOOP;
      END IF;
      RETURN NULL;
    END; $$;
    """)
    for table in ('waiting_list_entry', 'student_room_request', 'borrow_request'):
        op.execute(f'CREATE CONSTRAINT TRIGGER {table}_waiting_shape AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ras_waiting_changed()')


def downgrade():
    for table in ('waiting_list_entry', 'student_room_request', 'borrow_request'):
        op.execute(f'DROP TRIGGER {table}_waiting_shape ON {table}')
    op.execute('DROP FUNCTION ras_waiting_changed(); DROP FUNCTION ras_waiting_shape(bigint)')
    op.drop_table('waiting_list_entry')
    op.drop_constraint('ck_waiting_notice', 'application_state', type_='check')
    op.drop_column('application_state', 'waiting_notice_minutes')
