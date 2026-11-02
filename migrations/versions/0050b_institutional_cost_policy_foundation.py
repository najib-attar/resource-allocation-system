"""Empty institutional cost ledgers only; no governance commands or activation."""

from alembic import op
import sqlalchemy as sa

revision = '0050b'
down_revision = '0050a'
branch_labels = None
depends_on = None

TABLES = ('scheduling_cost_policy_authority_revision', 'scheduling_cost_policy_revision',
          'scheduling_cost_policy_event', 'scheduling_cost_policy_head')


def upgrade():
    op.create_table(TABLES[0],
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('university_user.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('capability', sa.String(16), primary_key=True),
        sa.Column('revision', sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column('decision', sa.String(12), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('university_user.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('effective_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False), sa.Column('authorization_ref', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint("capability IN ('propose','approve','audit')", name='ck_cost_authority_capability'),
        sa.CheckConstraint("decision IN ('Granted','Revoked')", name='ck_cost_authority_decision'),
        sa.CheckConstraint('revision > 0', name='ck_cost_authority_revision'),
        sa.CheckConstraint('isfinite(effective_from) AND isfinite(effective_until) AND effective_from < effective_until', name='ck_cost_authority_effective'),
        sa.CheckConstraint('length(btrim(reason)) BETWEEN 1 AND 2000', name='ck_cost_authority_reason'),
        sa.CheckConstraint('octet_length(authorization_ref) BETWEEN 1 AND 256 AND length(btrim(authorization_ref)) > 0', name='ck_cost_authority_reference'))
    op.create_table(TABLES[1],
        sa.Column('policy_id', sa.String(32), primary_key=True),
        sa.Column('revision', sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column('contract_version', sa.Integer(), nullable=False), sa.Column('objective_version', sa.Integer(), nullable=False),
        sa.Column('engine_operation', sa.String(32), nullable=False), sa.Column('objective_model', sa.String(64), nullable=False),
        sa.Column('rate_model', sa.String(64), nullable=False), sa.Column('timezone', sa.String(256), nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False), sa.Column('effective_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cost_unit', sa.Text(), nullable=False), sa.Column('calibration_ref', sa.Text(), nullable=False),
        sa.Column('provenance_type', sa.String(32), nullable=False), sa.Column('provenance_ref', sa.Text(), nullable=False),
        sa.Column('content_digest', sa.String(64), nullable=False),
        *(sa.Column(key, sa.Integer(), nullable=False) for key in ('preferred_rate', 'outside_window_rate', 'outside_day_rate',
            'gap_weight', 'nearby_limit', 'exception_fee', 'move_fixed_cost', 'move_participant_cost', 'delay_per_day')),
        sa.Column('proposer_id', sa.Integer(), sa.ForeignKey('university_user.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('proposer_capability', sa.String(16), nullable=False), sa.Column('proposer_authority_revision', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.ForeignKeyConstraint(('proposer_id', 'proposer_capability', 'proposer_authority_revision'),
            (TABLES[0] + '.user_id', TABLES[0] + '.capability', TABLES[0] + '.revision'), ondelete='RESTRICT'),
        sa.CheckConstraint("policy_id = 'university' AND revision > 0", name='ck_cost_policy_identity'),
        sa.CheckConstraint("contract_version = 1 AND objective_version = 1 AND engine_operation = 'cdmcs_schedule_v1' "
            "AND objective_model = 'V15_restricted_one_blocking_move' AND rate_model = 'weekday_window_tiers_v1'", name='ck_cost_policy_model'),
        sa.CheckConstraint("proposer_capability = 'propose' AND proposer_authority_revision > 0", name='ck_cost_policy_proposer'),
        sa.CheckConstraint("isfinite(effective_from) AND isfinite(effective_until) AND effective_from >= TIMESTAMPTZ '1970-01-01 00:00:00+00' "
            "AND effective_until < TIMESTAMPTZ '2100-01-01 00:00:00+00' AND effective_from < effective_until", name='ck_cost_policy_effective'),
        sa.CheckConstraint('preferred_rate BETWEEN 0 AND outside_window_rate AND outside_window_rate <= outside_day_rate AND outside_day_rate <= 100000000', name='ck_cost_policy_rates'),
        sa.CheckConstraint('gap_weight BETWEEN 0 AND 100000 AND nearby_limit BETWEEN 0 AND 10080', name='ck_cost_policy_gap'),
        sa.CheckConstraint('exception_fee BETWEEN 0 AND 10000000 AND move_fixed_cost BETWEEN 0 AND 10000000 '
            'AND move_participant_cost BETWEEN 0 AND 10000000 AND delay_per_day BETWEEN 0 AND 10000000', name='ck_cost_policy_fees'),
        sa.CheckConstraint("content_digest ~ '^[0-9a-f]{64}$'", name='ck_cost_policy_digest'),
        *(sa.CheckConstraint(f'octet_length({key}) BETWEEN 1 AND 256 AND length(btrim({key})) > 0', name='ck_cost_policy_' + key)
          for key in ('timezone', 'cost_unit', 'calibration_ref', 'provenance_ref')),
        sa.CheckConstraint("provenance_type = 'institutional_policy'", name='ck_cost_policy_provenance'))
    op.create_table(TABLES[2],
        sa.Column('id', sa.BigInteger(), sa.Identity(), primary_key=True), sa.Column('policy_id', sa.String(32), nullable=False),
        sa.Column('policy_revision', sa.BigInteger(), nullable=False), sa.Column('event_type', sa.String(16), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('university_user.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('actor_capability', sa.String(16), nullable=False), sa.Column('authority_revision', sa.BigInteger(), nullable=False),
        sa.Column('head_version', sa.BigInteger(), nullable=False),
        sa.Column('preceding_event_id', sa.BigInteger(), sa.ForeignKey(TABLES[2] + '.id', ondelete='RESTRICT')),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.ForeignKeyConstraint(('policy_id', 'policy_revision'), (TABLES[1] + '.policy_id', TABLES[1] + '.revision'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(('actor_id', 'actor_capability', 'authority_revision'),
            (TABLES[0] + '.user_id', TABLES[0] + '.capability', TABLES[0] + '.revision'), ondelete='RESTRICT'),
        sa.CheckConstraint("event_type IN ('Approved','Rejected','Activated','Deactivated')", name='ck_cost_event_type'),
        sa.CheckConstraint("actor_capability = 'approve' AND authority_revision > 0 AND head_version > 0", name='ck_cost_event_actor'),
        sa.CheckConstraint("(event_type IN ('Approved','Rejected') AND preceding_event_id IS NULL) OR "
            "(event_type IN ('Activated','Deactivated') AND preceding_event_id IS NOT NULL)", name='ck_cost_event_link'),
        sa.CheckConstraint('length(btrim(reason)) BETWEEN 1 AND 2000', name='ck_cost_event_reason'),
        sa.UniqueConstraint('head_version', name='uq_cost_event_head'))
    op.create_table(TABLES[3],
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('version', sa.BigInteger(), nullable=False),
        sa.Column('active_event_id', sa.BigInteger(), sa.ForeignKey(TABLES[2] + '.id', ondelete='RESTRICT')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint('id = 1 AND version >= 0', name='ck_cost_head_identity'))
    for table, name, columns in (
        (TABLES[0], 'ix_scheduling_cost_policy_authority_revision_actor_id', ['actor_id']),
        (TABLES[1], 'ix_cost_revision_proposer', ['proposer_id', 'proposer_capability', 'proposer_authority_revision']),
        (TABLES[2], 'ix_cost_event_actor', ['actor_id', 'actor_capability', 'authority_revision']),
        (TABLES[2], 'ix_cost_event_policy', ['policy_id', 'policy_revision']),
        (TABLES[2], 'ix_scheduling_cost_policy_event_preceding_event_id', ['preceding_event_id']),
        (TABLES[3], 'ix_scheduling_cost_policy_head_active_event_id', ['active_event_id'])):
        op.create_index(name, table, columns)
    op.execute("""
CREATE FUNCTION ras_cost_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Institutional policy history is immutable' USING ERRCODE='23514'; END; $$;
CREATE FUNCTION ras_cost_revision_validate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected text;
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_timezone_names WHERE name=NEW.timezone) THEN
  RAISE EXCEPTION 'Invalid policy timezone' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM scheduling_cost_policy_authority_revision
   WHERE user_id=NEW.proposer_id AND capability=NEW.proposer_capability
     AND revision=NEW.proposer_authority_revision AND decision='Granted') THEN
  RAISE EXCEPTION 'Policy proposer grant reference required' USING ERRCODE='23514';
 END IF;
 IF NEW.cost_unit ~ '[[:cntrl:]]' OR NEW.calibration_ref ~ '[[:cntrl:]]' OR NEW.provenance_ref ~ '[[:cntrl:]]' THEN
  RAISE EXCEPTION 'Invalid policy text' USING ERRCODE='23514';
 END IF;
 expected := encode(sha256(convert_to(jsonb_build_array(NEW.contract_version, NEW.provenance_type,
   NEW.policy_id, NEW.revision, NEW.objective_version, NEW.engine_operation, NEW.objective_model,
   NEW.rate_model, NEW.timezone, (extract(epoch FROM NEW.effective_from)*1000000)::bigint,
   (extract(epoch FROM NEW.effective_until)*1000000)::bigint, NEW.cost_unit, NEW.calibration_ref,
   NEW.provenance_type, NEW.provenance_ref, NEW.preferred_rate, NEW.outside_window_rate,
   NEW.outside_day_rate, NEW.gap_weight, NEW.nearby_limit, NEW.exception_fee,
   NEW.move_fixed_cost, NEW.move_participant_cost, NEW.delay_per_day)::text,'UTF8')),'hex');
 IF NEW.content_digest IS DISTINCT FROM expected THEN
  RAISE EXCEPTION 'Policy digest mismatch' USING ERRCODE='23514';
 END IF;
 NEW.created_at := clock_timestamp(); RETURN NEW;
END; $$;
CREATE FUNCTION ras_cost_event_validate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE proposer integer; previous record;
BEGIN
 SELECT proposer_id INTO proposer FROM scheduling_cost_policy_revision
   WHERE policy_id=NEW.policy_id AND revision=NEW.policy_revision;
 IF NEW.event_type='Approved' AND NEW.actor_id=proposer THEN
  RAISE EXCEPTION 'Separate policy approver required' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM scheduling_cost_policy_authority_revision
   WHERE user_id=NEW.actor_id AND capability=NEW.actor_capability
     AND revision=NEW.authority_revision AND decision='Granted') THEN
  RAISE EXCEPTION 'Policy actor grant reference required' USING ERRCODE='23514';
 END IF;
 IF NEW.preceding_event_id IS NOT NULL THEN
  SELECT * INTO previous FROM scheduling_cost_policy_event WHERE id=NEW.preceding_event_id;
  IF previous.id IS NULL OR previous.policy_id<>NEW.policy_id OR previous.policy_revision<>NEW.policy_revision
    OR previous.head_version>=NEW.head_version
    OR (NEW.event_type='Activated' AND previous.event_type<>'Approved')
    OR (NEW.event_type='Deactivated' AND previous.event_type<>'Activated') THEN
   RAISE EXCEPTION 'Invalid policy event association' USING ERRCODE='23514';
  END IF;
 END IF;
 NEW.created_at := clock_timestamp(); RETURN NEW;
END; $$;
CREATE FUNCTION ras_cost_head_validate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND (OLD.version=9223372036854775807 OR NEW.version<>OLD.version+1) THEN
  RAISE EXCEPTION 'Policy head revision conflict' USING ERRCODE='23514';
 END IF;
 IF NEW.active_event_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM scheduling_cost_policy_event
   WHERE id=NEW.active_event_id AND event_type='Activated' AND head_version<=NEW.version) THEN
  RAISE EXCEPTION 'Policy head requires explicit activation history' USING ERRCODE='23514';
 END IF;
 NEW.updated_at := clock_timestamp(); RETURN NEW;
END; $$;
CREATE FUNCTION ras_cost_authority_timestamp() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.created_at := clock_timestamp(); RETURN NEW; END; $$;
CREATE TRIGGER cost_revision_validate BEFORE INSERT ON scheduling_cost_policy_revision
 FOR EACH ROW EXECUTE FUNCTION ras_cost_revision_validate();
CREATE TRIGGER cost_event_validate BEFORE INSERT ON scheduling_cost_policy_event
 FOR EACH ROW EXECUTE FUNCTION ras_cost_event_validate();
CREATE TRIGGER cost_head_validate BEFORE INSERT OR UPDATE ON scheduling_cost_policy_head
 FOR EACH ROW EXECUTE FUNCTION ras_cost_head_validate();
CREATE TRIGGER cost_authority_timestamp BEFORE INSERT ON scheduling_cost_policy_authority_revision
 FOR EACH ROW EXECUTE FUNCTION ras_cost_authority_timestamp();
CREATE TRIGGER cost_head_no_delete BEFORE DELETE ON scheduling_cost_policy_head
 FOR EACH ROW EXECUTE FUNCTION ras_cost_history_immutable();
CREATE TRIGGER cost_head_no_truncate BEFORE TRUNCATE ON scheduling_cost_policy_head
 FOR EACH STATEMENT EXECUTE FUNCTION ras_cost_history_immutable();
""")
    for table, prefix in zip(TABLES[:3], ('cost_authority', 'cost_revision', 'cost_event')):
        op.execute(f'CREATE TRIGGER {prefix}_immutable BEFORE UPDATE OR DELETE ON {table} '
                   'FOR EACH ROW EXECUTE FUNCTION ras_cost_history_immutable()')
        op.execute(f'CREATE TRIGGER {prefix}_no_truncate BEFORE TRUNCATE ON {table} '
                   'FOR EACH STATEMENT EXECUTE FUNCTION ras_cost_history_immutable()')
    schema = op.get_bind().scalar(sa.text('SELECT current_schema()'))
    quoted = op.get_bind().dialect.identifier_preparer.quote(schema)
    for function in ('ras_cost_revision_validate', 'ras_cost_event_validate', 'ras_cost_head_validate',
                     'ras_cost_authority_timestamp', 'ras_cost_history_immutable'):
        op.execute(f'ALTER FUNCTION {function}() SET search_path TO {quoted}, pg_catalog')


def downgrade():
    # One lock statement takes every lock before any emptiness check or DROP.
    op.execute('LOCK TABLE ' + ', '.join(reversed(TABLES)) + ' IN ACCESS EXCLUSIVE MODE')
    for table in TABLES:
        if op.get_bind().scalar(sa.text('SELECT EXISTS(SELECT 1 FROM ' + table + ')')):
            raise RuntimeError('Downgrade would discard institutional policy history or state. Authorized retention review is required.')
    for table in reversed(TABLES):
        op.drop_table(table)
    for function in ('ras_cost_revision_validate', 'ras_cost_event_validate', 'ras_cost_head_validate',
                     'ras_cost_authority_timestamp', 'ras_cost_history_immutable'):
        op.execute('DROP FUNCTION ' + function + '()')
