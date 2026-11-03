"""Explicit eligibility; legacy remains unreviewed and existing publications untouched."""
from alembic import op
import sqlalchemy as sa

revision = '0051a'
down_revision = '0050b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('resource_request', sa.Column('faculty_declaration', sa.Text(), nullable=False, server_default=''))
    bind = op.get_bind()
    op.create_table('request_eligibility',
        sa.Column('request_id',sa.Integer(),sa.ForeignKey('resource_request.id'),primary_key=True),
        sa.Column('origin',sa.String(24),nullable=False,server_default='Repository'),
        sa.Column('submitted_by',sa.Integer(),sa.ForeignKey('university_user.id')),
        sa.Column('legacy_revision',sa.Integer()),
        sa.Column('status',sa.String(40),nullable=False,server_default='Pending Eligibility Review'),
        sa.Column('version',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('reviewed_revision',sa.Integer()),
        sa.Column('reviewer_id',sa.Integer(),sa.ForeignKey('university_user.id')),
        sa.Column('reason',sa.Text(),nullable=False,server_default=''),
        sa.Column('decided_at',sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('Pending Eligibility Review','Eligible','Eligibility Rejected')",name='ck_eligibility_status'),
        sa.CheckConstraint("origin IN ('Legacy','Repository','Import','Demo','Professor','Administration')",name='ck_eligibility_origin'),
        sa.CheckConstraint('version >= 0',name='ck_eligibility_version'),
        sa.CheckConstraint("origin <> 'Professor' OR submitted_by IS NOT NULL",name='ck_eligibility_submitter'),
        sa.CheckConstraint("(status = 'Pending Eligibility Review' AND reviewed_revision IS NULL AND reviewer_id IS NULL AND decided_at IS NULL) OR "
            "(status <> 'Pending Eligibility Review' AND reviewed_revision > 0 AND reviewer_id IS NOT NULL AND decided_at IS NOT NULL AND length(btrim(reason)) BETWEEN 1 AND 2000)",name='ck_eligibility_decision'))
    op.create_table('eligibility_event',
        sa.Column('id',sa.BigInteger(),sa.Identity(),primary_key=True),
        sa.Column('request_id',sa.Integer(),sa.ForeignKey('resource_request.id'),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),sa.Column('request_revision',sa.Integer(),nullable=False),
        sa.Column('status',sa.String(40),nullable=False),sa.Column('origin',sa.String(24),nullable=False),
        sa.Column('actor_id',sa.Integer(),sa.ForeignKey('university_user.id')),
        sa.Column('reason',sa.Text(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('request_id','version',name='uq_eligibility_event_version'))
    op.create_table('allocation_eligibility',
        sa.Column('run_id',sa.BigInteger(),sa.ForeignKey('allocation_run.id'),primary_key=True),
        sa.Column('request_id',sa.Integer(),sa.ForeignKey('resource_request.id'),primary_key=True),
        sa.Column('request_revision',sa.Integer(),nullable=False),sa.Column('eligibility_version',sa.Integer(),nullable=False))
    for table,column in (('request_eligibility','submitted_by'),('request_eligibility','reviewer_id'),('request_eligibility','status'),
                         ('eligibility_event','request_id'),('eligibility_event','actor_id'),('allocation_eligibility','request_id')):
        op.create_index('ix_'+table+'_'+column,table,[column])
    op.execute("INSERT INTO request_eligibility (request_id, origin, legacy_revision) SELECT id, 'Legacy', revision FROM resource_request")
    op.execute("INSERT INTO eligibility_event (request_id, version, request_revision, status, origin, reason) "
               "SELECT r.id, 0, r.revision, e.status, e.origin, 'Legacy provenance is unverified; no eligibility approval inferred.' "
               "FROM resource_request r JOIN request_eligibility e ON e.request_id=r.id")
    op.execute('UPDATE application_state SET input_revision=input_revision+1 WHERE id=1 AND EXISTS(SELECT 1 FROM resource_request)')
    op.execute("""
    CREATE FUNCTION ras_eligibility_changed() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE owner_id integer; current_revision integer; actor integer;
    BEGIN
        -- All academic input/review writers share this serialization point with start_run/publish_run.
        PERFORM id FROM application_state WHERE id=1 FOR UPDATE;
        SELECT requester_id, revision INTO owner_id, current_revision FROM resource_request WHERE id=NEW.request_id;
        IF TG_OP='UPDATE' THEN
            IF NEW.request_id <> OLD.request_id OR NEW.version <> OLD.version+1
               OR ((NEW.origin,NEW.submitted_by,NEW.legacy_revision) IS DISTINCT FROM (OLD.origin,OLD.submitted_by,OLD.legacy_revision)
                   AND NOT (OLD.origin='Repository' AND OLD.version=0 AND OLD.status='Pending Eligibility Review'
                            AND NEW.status='Pending Eligibility Review')) THEN
                RAISE EXCEPTION 'Eligibility identity/version is immutable or stale' USING ERRCODE='23514';
            END IF;
        ELSIF NEW.status <> 'Pending Eligibility Review' THEN
            RAISE EXCEPTION 'New eligibility must await review' USING ERRCODE='23514';
        END IF;
        IF NEW.status <> 'Pending Eligibility Review' THEN
            IF NEW.reviewed_revision IS DISTINCT FROM current_revision OR NEW.reviewer_id=owner_id OR NOT EXISTS (
                SELECT 1 FROM login_account a JOIN university_user u ON u.id=a.user_id JOIN role ro ON ro.id=u.primary_role_id
                WHERE a.user_id=NEW.reviewer_id AND a.enabled AND lower(u.status)='active'
                AND (a.administrator OR ro.name='Administrator')) THEN
                RAISE EXCEPTION 'A different active administrator must review the current revision' USING ERRCODE='23514';
            END IF;
        END IF;
        RETURN NEW;
    END; $$;
    CREATE TRIGGER eligibility_guard BEFORE INSERT OR UPDATE ON request_eligibility
        FOR EACH ROW EXECUTE FUNCTION ras_eligibility_changed();
    CREATE FUNCTION ras_eligibility_audit() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE rev integer;
    BEGIN
        SELECT revision INTO rev FROM resource_request WHERE id=NEW.request_id;
        INSERT INTO eligibility_event(request_id,version,request_revision,status,origin,actor_id,reason)
            VALUES(NEW.request_id,NEW.version,rev,NEW.status,NEW.origin,
                CASE WHEN NEW.status <> 'Pending Eligibility Review' THEN NEW.reviewer_id
                     WHEN TG_OP='UPDATE' AND OLD.origin='Repository' AND NEW.origin='Professor' THEN NEW.submitted_by
                     ELSE NULL END,NEW.reason);
        UPDATE application_state SET input_revision=input_revision+1 WHERE id=1;
        RETURN NULL;
    END; $$;
    CREATE TRIGGER eligibility_audit AFTER INSERT OR UPDATE ON request_eligibility
        FOR EACH ROW EXECUTE FUNCTION ras_eligibility_audit();
    CREATE FUNCTION ras_eligibility_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Eligibility audit/provenance cannot be deleted or rewritten' USING ERRCODE='23514'; END; $$;
    CREATE TRIGGER eligibility_event_immutable BEFORE UPDATE OR DELETE ON eligibility_event
        FOR EACH ROW EXECUTE FUNCTION ras_eligibility_immutable();
    CREATE TRIGGER eligibility_no_delete BEFORE DELETE ON request_eligibility
        FOR EACH ROW EXECUTE FUNCTION ras_eligibility_immutable();
    CREATE TRIGGER eligibility_no_truncate BEFORE TRUNCATE ON request_eligibility
        FOR EACH STATEMENT EXECUTE FUNCTION ras_eligibility_immutable();
    CREATE TRIGGER eligibility_event_no_truncate BEFORE TRUNCATE ON eligibility_event
        FOR EACH STATEMENT EXECUTE FUNCTION ras_eligibility_immutable();
    CREATE TRIGGER allocation_eligibility_immutable BEFORE UPDATE OR DELETE ON allocation_eligibility
        FOR EACH ROW EXECUTE FUNCTION ras_eligibility_immutable();
    CREATE TRIGGER allocation_eligibility_no_truncate BEFORE TRUNCATE ON allocation_eligibility
        FOR EACH STATEMENT EXECUTE FUNCTION ras_eligibility_immutable();
    CREATE FUNCTION ras_request_eligibility() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP='INSERT' THEN
            INSERT INTO request_eligibility(request_id) VALUES(NEW.id);
        ELSIF NEW.revision IS DISTINCT FROM OLD.revision THEN
            UPDATE request_eligibility SET status='Pending Eligibility Review', version=version+1,
                reviewed_revision=NULL, reviewer_id=NULL, decided_at=NULL, reason='Material revision requires a new eligibility review.'
                WHERE request_id=NEW.id;
        END IF;
        RETURN NULL;
    END; $$;
    CREATE TRIGGER request_eligibility AFTER INSERT OR UPDATE ON resource_request
        FOR EACH ROW EXECUTE FUNCTION ras_request_eligibility();
    CREATE FUNCTION ras_material_revision() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF (NEW.type,NEW.requester_id,NEW.resource_id,NEW.participant_count,NEW.title,NEW.purpose,
            NEW.required_feature,NEW.required_building,NEW.faculty_declaration,NEW.revision)
           IS DISTINCT FROM (OLD.type,OLD.requester_id,OLD.resource_id,OLD.participant_count,OLD.title,OLD.purpose,
            OLD.required_feature,OLD.required_building,OLD.faculty_declaration,OLD.revision) THEN
            PERFORM id FROM application_state WHERE id=1 FOR UPDATE;
            IF NEW.requester_id <> OLD.requester_id AND EXISTS (
                SELECT 1 FROM request_eligibility WHERE request_id=OLD.id AND origin='Professor') THEN
                RAISE EXCEPTION 'Professor request ownership is immutable' USING ERRCODE='23514';
            END IF;
            IF EXISTS (SELECT 1 FROM request_decision a JOIN application_state s ON s.active_run_id=a.run_id
                       WHERE a.request_id=OLD.id) THEN
                RAISE EXCEPTION 'Published reservations are read-only; a replacement workflow is required' USING ERRCODE='23514';
            END IF;
            NEW.revision := greatest(NEW.revision,OLD.revision+1);
        END IF;
        RETURN NEW;
    END; $$;
    CREATE TRIGGER request_material_revision BEFORE UPDATE ON resource_request
        FOR EACH ROW EXECUTE FUNCTION ras_material_revision();
    CREATE FUNCTION ras_child_eligibility() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE key integer;
    BEGIN
        FOR key IN SELECT DISTINCT x FROM unnest(CASE WHEN TG_OP='INSERT' THEN ARRAY[NEW.request_id]
            WHEN TG_OP='DELETE' THEN ARRAY[OLD.request_id] ELSE ARRAY[OLD.request_id,NEW.request_id] END) x ORDER BY x LOOP
            PERFORM id FROM application_state WHERE id=1 FOR UPDATE;
            IF EXISTS (SELECT 1 FROM request_decision a JOIN application_state s ON s.active_run_id=a.run_id WHERE a.request_id=key) THEN
                RAISE EXCEPTION 'Published reservation inputs are read-only' USING ERRCODE='23514';
            END IF;
            -- Service revisions always bump the parent. Also invalidate direct child-table edits of reviewed inputs.
            IF EXISTS (SELECT 1 FROM request_eligibility WHERE request_id=key AND reviewed_revision IS NOT NULL) THEN
                UPDATE resource_request SET revision=revision+1 WHERE id=key;
            END IF;
        END LOOP;
        IF TG_OP='DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END; $$;
    CREATE FUNCTION ras_allocation_eligibility_start() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        PERFORM id FROM application_state WHERE id=1 FOR UPDATE;
        IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.snapshot->'requests') j
            LEFT JOIN resource_request r ON r.id=(j->>'id')::integer
            LEFT JOIN request_eligibility e ON e.request_id=r.id
            WHERE r.id IS NULL OR e.status IS DISTINCT FROM 'Eligible' OR e.reviewed_revision IS DISTINCT FROM r.revision) THEN
            RAISE EXCEPTION 'Allocation snapshot contains unreviewed or rejected requests' USING ERRCODE='23514';
        END IF;
        IF EXISTS (SELECT 1 FROM request_decision d JOIN application_state s ON s.active_run_id=d.run_id
            JOIN resource_request r ON r.id=d.request_id JOIN request_eligibility e ON e.request_id=r.id
            WHERE e.origin='Legacy' AND (e.status='Pending Eligibility Review' OR e.reviewed_revision IS DISTINCT FROM r.revision)) THEN
            RAISE EXCEPTION 'Legacy review is outstanding; existing publication is preserved' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END; $$;
    CREATE TRIGGER allocation_eligibility_start BEFORE INSERT ON allocation_run
        FOR EACH ROW EXECUTE FUNCTION ras_allocation_eligibility_start();
    CREATE FUNCTION ras_allocation_eligibility_publish() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE candidate allocation_run%ROWTYPE; eligible_count bigint; proof_count bigint;
    BEGIN
        IF NEW.active_run_id IS NOT DISTINCT FROM OLD.active_run_id THEN RETURN NEW; END IF;
        IF NEW.active_run_id IS NULL THEN
            RAISE EXCEPTION 'Published reservations require an authorized replacement publication' USING ERRCODE='23514';
        END IF;
        SELECT * INTO candidate FROM allocation_run WHERE id=NEW.active_run_id;
        IF candidate.status <> 'success' OR candidate.input_revision <> NEW.input_revision THEN
            RAISE EXCEPTION 'Allocation publication is stale or unsuccessful' USING ERRCODE='23514';
        END IF;
        SELECT count(*) INTO eligible_count FROM resource_request r JOIN request_eligibility e ON e.request_id=r.id
            WHERE e.status='Eligible' AND e.reviewed_revision=r.revision;
        SELECT count(*) INTO proof_count FROM allocation_eligibility p JOIN resource_request r ON r.id=p.request_id
            JOIN request_eligibility e ON e.request_id=r.id WHERE p.run_id=NEW.active_run_id
            AND e.status='Eligible' AND e.reviewed_revision=r.revision AND p.request_revision=r.revision AND p.eligibility_version=e.version;
        IF proof_count <> eligible_count OR proof_count <> jsonb_array_length(candidate.snapshot->'requests')
           OR EXISTS (SELECT 1 FROM jsonb_array_elements(candidate.snapshot->'requests') j
              WHERE NOT EXISTS (SELECT 1 FROM allocation_eligibility p WHERE p.run_id=NEW.active_run_id AND p.request_id=(j->>'id')::integer)) THEN
            RAISE EXCEPTION 'Allocation publication lacks current eligibility proof' USING ERRCODE='23514';
        END IF;
        IF EXISTS (SELECT 1 FROM request_decision d JOIN resource_request r ON r.id=d.request_id
            JOIN request_eligibility e ON e.request_id=r.id WHERE d.run_id=OLD.active_run_id AND e.origin='Legacy'
            AND (e.status='Pending Eligibility Review' OR e.reviewed_revision IS DISTINCT FROM r.revision)) THEN
            RAISE EXCEPTION 'Legacy review is outstanding; existing publication is preserved' USING ERRCODE='23514';
        END IF;
        RETURN NEW;
    END; $$;
    CREATE TRIGGER allocation_eligibility_publish BEFORE UPDATE OF active_run_id ON application_state
        FOR EACH ROW EXECUTE FUNCTION ras_allocation_eligibility_publish();
    """)
    for table in ('request_slot','request_participant','exam_details'):
        op.execute(f"CREATE TRIGGER {table}_eligibility BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION ras_child_eligibility()")
    schema = bind.dialect.identifier_preparer.quote(bind.exec_driver_sql('SELECT current_schema()').scalar_one())
    for name in ('ras_eligibility_changed','ras_eligibility_audit','ras_eligibility_immutable',
                 'ras_request_eligibility','ras_material_revision','ras_child_eligibility',
                 'ras_allocation_eligibility_start','ras_allocation_eligibility_publish'):
        op.execute(f'ALTER FUNCTION {name}() SET search_path = {schema}, pg_catalog, pg_temp')


def downgrade():
    op.execute('LOCK TABLE application_state, resource_request, request_slot, exam_details, request_participant, '
               'request_eligibility, eligibility_event, allocation_eligibility, allocation_run IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().exec_driver_sql('SELECT EXISTS(SELECT 1 FROM request_eligibility)').scalar_one():
        raise RuntimeError('Eligibility downgrade with request/audit data requires a separately reviewed archival and rollback procedure.')
    for table,name in (('request_eligibility','eligibility_guard'),('request_eligibility','eligibility_audit'),
            ('request_eligibility','eligibility_no_delete'),('eligibility_event','eligibility_event_immutable'),
            ('request_eligibility','eligibility_no_truncate'),('eligibility_event','eligibility_event_no_truncate'),
            ('allocation_eligibility','allocation_eligibility_immutable'),('allocation_eligibility','allocation_eligibility_no_truncate'),
            ('resource_request','request_material_revision'),('resource_request','request_eligibility'),
            ('allocation_run','allocation_eligibility_start'),('application_state','allocation_eligibility_publish')):
        op.execute(f'DROP TRIGGER {name} ON {table}')
    for table in ('request_slot','request_participant','exam_details'):
        op.execute(f'DROP TRIGGER {table}_eligibility ON {table}')
    for name in ('ras_eligibility_changed','ras_eligibility_audit','ras_eligibility_immutable','ras_request_eligibility',
            'ras_material_revision','ras_child_eligibility','ras_allocation_eligibility_start','ras_allocation_eligibility_publish'):
        op.execute(f'DROP FUNCTION {name}()')
    for table in ('allocation_eligibility','eligibility_event','request_eligibility'):
        op.drop_table(table)
    op.drop_column('resource_request','faculty_declaration')
