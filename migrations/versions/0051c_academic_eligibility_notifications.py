"""Allow private Inbox receipts for recorded professor eligibility decisions."""
from alembic import op
import sqlalchemy as sa


revision = '0051c'
down_revision = '0051b'
branch_labels = None
depends_on = None

EXISTING_SOURCES = "appointment_event_id, room_event_id, equipment_event_id, feedback_event_id"


def upgrade():
    op.add_column('notification', sa.Column('eligibility_event_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_notification_eligibility_event_id_eligibility_event',
        'notification', 'eligibility_event', ['eligibility_event_id'], ['id'])
    op.create_unique_constraint('uq_notification_recipient_id_eligibility_event_id',
        'notification', ['recipient_id', 'eligibility_event_id'])
    op.create_index('ix_notification_eligibility_event_id', 'notification', ['eligibility_event_id'])
    op.drop_constraint('ck_notification_source', 'notification', type_='check')
    op.create_check_constraint('ck_notification_source', 'notification',
        f'num_nonnulls({EXISTING_SOURCES}, eligibility_event_id) = 1')


def downgrade():
    op.execute('LOCK TABLE notification IN ACCESS EXCLUSIVE MODE')
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM notification WHERE eligibility_event_id IS NOT NULL)')):
        raise RuntimeError('Cannot discard academic eligibility notices. Keep this migration to preserve Inbox history.')
    op.drop_constraint('ck_notification_source', 'notification', type_='check')
    op.create_check_constraint('ck_notification_source', 'notification', f'num_nonnulls({EXISTING_SOURCES}) = 1')
    op.drop_index('ix_notification_eligibility_event_id', table_name='notification')
    op.drop_constraint('uq_notification_recipient_id_eligibility_event_id', 'notification', type_='unique')
    op.drop_constraint('fk_notification_eligibility_event_id_eligibility_event', 'notification', type_='foreignkey')
    op.drop_column('notification', 'eligibility_event_id')
