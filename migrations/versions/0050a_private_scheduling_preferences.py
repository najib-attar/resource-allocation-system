"""Private self-owned preference revisions; no scheduling integration or defaults."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0050a'
down_revision = '0049b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('scheduling_preference_revision',
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('university_user.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('revision', sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column('contract_version', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('timezone', sa.String(256)),
        sa.Column('effective_from', sa.Date()), sa.Column('effective_until', sa.Date()),
        sa.Column('preferred_weekdays', postgresql.JSONB(none_as_null=True)),
        sa.Column('preferred_windows', postgresql.JSONB(none_as_null=True)),
        sa.Column('gap_indifferent', sa.Boolean()), sa.Column('desired_gap_minutes', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.CheckConstraint('revision > 0 AND contract_version > 0', name='ck_preference_revision'),
        sa.CheckConstraint("status IN ('configured','deactivated')", name='ck_preference_status'),
        sa.CheckConstraint("(status = 'deactivated' AND timezone IS NULL AND effective_from IS NULL AND effective_until IS NULL "
                           "AND preferred_weekdays IS NULL AND preferred_windows IS NULL AND gap_indifferent IS NULL AND desired_gap_minutes IS NULL) OR "
                           "(status = 'configured' AND timezone IS NOT NULL AND effective_from IS NOT NULL AND effective_until IS NOT NULL "
                           "AND preferred_weekdays IS NOT NULL AND preferred_windows IS NOT NULL AND gap_indifferent IS NOT NULL "
                           "AND ((gap_indifferent AND desired_gap_minutes IS NULL) OR (NOT gap_indifferent AND desired_gap_minutes IS NOT NULL)))",
                           name='ck_preference_shape'),
        sa.CheckConstraint('octet_length(timezone) BETWEEN 1 AND 256', name='ck_preference_timezone'),
        sa.CheckConstraint("effective_from >= DATE '1970-01-01' AND effective_from <= effective_until AND effective_until < DATE '2100-01-01'", name='ck_preference_dates'),
        sa.CheckConstraint("jsonb_typeof(preferred_weekdays) = 'array' AND jsonb_array_length(preferred_weekdays) <= 7 "
                           "AND '[1,2,3,4,5,6,7]'::jsonb @> preferred_weekdays", name='ck_preference_weekdays'),
        sa.CheckConstraint("jsonb_typeof(preferred_windows) = 'array' AND jsonb_array_length(preferred_windows) <= 64 "
                           "AND octet_length(preferred_windows::text) <= 16384", name='ck_preference_windows'),
        sa.CheckConstraint('desired_gap_minutes BETWEEN 0 AND 1440', name='ck_preference_gap'))
    op.execute("""
CREATE FUNCTION ras_preference_history_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Preference revision history is immutable' USING ERRCODE='23514';
END; $$;
CREATE TRIGGER preference_history_immutable BEFORE UPDATE OR DELETE ON scheduling_preference_revision
 FOR EACH ROW EXECUTE FUNCTION ras_preference_history_immutable();
CREATE TRIGGER preference_history_no_truncate BEFORE TRUNCATE ON scheduling_preference_revision
 FOR EACH STATEMENT EXECUTE FUNCTION ras_preference_history_immutable();
""")


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS(SELECT 1 FROM scheduling_preference_revision)')):
        raise RuntimeError('Downgrade would discard private preference history. Authorized retention/erasure review is required first.')
    op.drop_table('scheduling_preference_revision')
    op.execute('DROP FUNCTION ras_preference_history_immutable()')
