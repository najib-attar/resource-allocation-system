"""Private, transactional event notifications and durable read state."""

from alembic import op
import sqlalchemy as sa

revision = '0043c'
down_revision = '0043b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('notification',
        sa.Column('id', sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column('recipient_id', sa.Integer(), nullable=False),
        sa.Column('appointment_event_id', sa.BigInteger(), nullable=True),
        sa.Column('room_event_id', sa.BigInteger(), nullable=True),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_notification'),
        sa.ForeignKeyConstraint(['recipient_id'], ['university_user.id'], name='fk_notification_recipient_id_university_user'),
        sa.ForeignKeyConstraint(['appointment_event_id'], ['appointment_event.id'], name='fk_notification_appointment_event_id_appointment_event'),
        sa.ForeignKeyConstraint(['room_event_id'], ['room_event.id'], name='fk_notification_room_event_id_room_event'),
        sa.CheckConstraint('num_nonnulls(appointment_event_id, room_event_id) = 1', name='ck_notification_source'),
        sa.UniqueConstraint('recipient_id', 'appointment_event_id', name='uq_notification_recipient_id_appointment_event_id'),
        sa.UniqueConstraint('recipient_id', 'room_event_id', name='uq_notification_recipient_id_room_event_id'))
    op.create_index('ix_notification_recipient_read_id', 'notification', ['recipient_id', 'read_at', 'id'])
    op.create_index('ix_notification_appointment_event_id', 'notification', ['appointment_event_id'])
    op.create_index('ix_notification_room_event_id', 'notification', ['room_event_id'])
    # Preserve existing updates for currently authorized participants, never a broadcast.
    op.execute("""
        INSERT INTO notification(recipient_id, appointment_event_id)
        SELECT DISTINCT people.user_id, event.id FROM appointment_event event
        JOIN (
            SELECT id AS appointment_id, organizer_id AS user_id FROM appointment
            UNION SELECT appointment_id, user_id FROM appointment_professor
            UNION SELECT appointment_id, user_id FROM appointment_invitation
        ) people ON people.appointment_id=event.appointment_id
        WHERE people.user_id<>event.actor_id;
        INSERT INTO notification(recipient_id, room_event_id)
        SELECT DISTINCT people.user_id, event.id FROM room_event event
        JOIN (
            SELECT id AS request_id, organizer_id AS user_id FROM student_room_request
            UNION SELECT id, approver_id FROM student_room_request
            UNION SELECT request_id, user_id FROM room_invitation
        ) people ON people.request_id=event.request_id
        WHERE people.user_id<>event.actor_id;
    """)


def downgrade():
    op.drop_index('ix_notification_room_event_id', table_name='notification')
    op.drop_index('ix_notification_appointment_event_id', table_name='notification')
    op.drop_index('ix_notification_recipient_read_id', table_name='notification')
    op.drop_table('notification')
