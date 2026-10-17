"""equipment inventory and borrowing"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0044a'
down_revision = '0043c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('equipment_category',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('equipment_type',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('faculty_id', sa.Integer(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('specifications', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('max_loan_days', sa.Integer(), nullable=False),
    sa.Column('eligible_faculty_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('pickup_instructions', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.CheckConstraint("jsonb_typeof(specifications) = 'object' AND jsonb_typeof(eligible_faculty_ids) = 'array'"),
    sa.CheckConstraint('max_loan_days BETWEEN 1 AND 365'),
    sa.ForeignKeyConstraint(['category_id'], ['equipment_category.id'], ),
    sa.ForeignKeyConstraint(['faculty_id'], ['organization_unit.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'faculty_id')
    )
    op.create_index(op.f('ix_equipment_type_category_id'), 'equipment_type', ['category_id'], unique=False)
    op.create_index(op.f('ix_equipment_type_faculty_id'), 'equipment_type', ['faculty_id'], unique=False)
    op.create_table('borrow_request',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('borrower_id', sa.Integer(), nullable=False),
    sa.Column('faculty_id', sa.Integer(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('submission_key', sa.String(length=32), nullable=False),
    sa.Column('submission_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('Pending Approval','Approved','Rejected','Borrowed','Partially Returned','Returned','Cancelled')"),
    sa.CheckConstraint("submission_key ~ '^[0-9a-f]{32}$' AND submission_fingerprint ~ '^[0-9a-f]{64}$'"),
    sa.CheckConstraint('start_at < due_at'),
    sa.ForeignKeyConstraint(['borrower_id'], ['university_user.id'], ),
    sa.ForeignKeyConstraint(['faculty_id'], ['organization_unit.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('borrower_id', 'submission_key'),
    sa.UniqueConstraint('id', 'faculty_id')
    )
    op.create_index('ix_borrow_faculty_status', 'borrow_request', ['faculty_id', 'status'], unique=False)
    op.create_index(op.f('ix_borrow_request_borrower_id'), 'borrow_request', ['borrower_id'], unique=False)
    op.create_table('equipment_unit',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('type_id', sa.Integer(), nullable=False),
    sa.Column('asset_tag', sa.String(length=150), nullable=False),
    sa.Column('condition', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.CheckConstraint("condition IN ('usable','maintenance','damaged','missing','lost','retired')"),
    sa.ForeignKeyConstraint(['type_id'], ['equipment_type.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('asset_tag'),
    sa.UniqueConstraint('id', 'type_id')
    )
    op.create_index(op.f('ix_equipment_unit_type_id'), 'equipment_unit', ['type_id'], unique=False)
    op.create_table('borrow_extension',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('decided_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('Pending','Approved','Rejected')"),
    sa.ForeignKeyConstraint(['decided_by'], ['login_account.user_id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['borrow_request.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_borrow_extension_decided_by'), 'borrow_extension', ['decided_by'], unique=False)
    op.create_index(op.f('ix_borrow_extension_request_id'), 'borrow_extension', ['request_id'], unique=False)
    op.create_index('uq_pending_borrow_extension', 'borrow_extension', ['request_id'], unique=True, postgresql_where="status = 'Pending'")
    op.create_table('borrow_item',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('faculty_id', sa.Integer(), nullable=False),
    sa.Column('type_id', sa.Integer(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('specifications', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("quantity BETWEEN 1 AND 1000 AND jsonb_typeof(specifications) = 'object'"),
    sa.ForeignKeyConstraint(['request_id', 'faculty_id'], ['borrow_request.id', 'borrow_request.faculty_id'], ),
    sa.ForeignKeyConstraint(['type_id', 'faculty_id'], ['equipment_type.id', 'equipment_type.faculty_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'type_id'),
    sa.UniqueConstraint('request_id', 'type_id')
    )
    op.create_index(op.f('ix_borrow_item_faculty_id'), 'borrow_item', ['faculty_id'], unique=False)
    op.create_index(op.f('ix_borrow_item_request_id'), 'borrow_item', ['request_id'], unique=False)
    op.create_index(op.f('ix_borrow_item_type_id'), 'borrow_item', ['type_id'], unique=False)
    op.create_table('equipment_custodian',
    sa.Column('faculty_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['faculty_id'], ['organization_unit.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['login_account.user_id'], ),
    sa.PrimaryKeyConstraint('faculty_id')
    )
    op.create_index(op.f('ix_equipment_custodian_user_id'), 'equipment_custodian', ['user_id'], unique=False)
    op.create_table('equipment_event',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('faculty_id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=True),
    sa.Column('unit_id', sa.Integer(), nullable=True),
    sa.Column('actor_id', sa.Integer(), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['university_user.id'], ),
    sa.ForeignKeyConstraint(['faculty_id'], ['organization_unit.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['borrow_request.id'], ),
    sa.ForeignKeyConstraint(['unit_id'], ['equipment_unit.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_equipment_event_actor_id'), 'equipment_event', ['actor_id'], unique=False)
    op.create_index(op.f('ix_equipment_event_faculty_id'), 'equipment_event', ['faculty_id'], unique=False)
    op.create_index(op.f('ix_equipment_event_request_id'), 'equipment_event', ['request_id'], unique=False)
    op.create_index(op.f('ix_equipment_event_unit_id'), 'equipment_event', ['unit_id'], unique=False)
    op.create_table('equipment_reservation',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('type_id', sa.Integer(), nullable=False),
    sa.Column('unit_id', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period', postgresql.TSTZRANGE(), sa.Computed("tstzrange(start_at, due_at, '[)')", persisted=True), nullable=False),
    sa.Column('released', sa.Boolean(), nullable=False),
    sa.Column('handed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('handed_by', sa.Integer(), nullable=True),
    sa.Column('handover_condition', sa.Text(), nullable=True),
    sa.Column('returned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_by', sa.Integer(), nullable=True),
    sa.Column('return_condition', sa.Text(), nullable=True),
    postgresql.ExcludeConstraint((sa.column('unit_id'), '='), (sa.column('period'), '&&'), where=sa.text('NOT released'), using='gist', name='ex_equipment_overlap'),
    sa.CheckConstraint('handed_at IS NULL OR (handed_by IS NOT NULL AND handover_condition IS NOT NULL)'),
    sa.CheckConstraint('returned_at IS NULL OR (handed_at IS NOT NULL AND returned_at >= handed_at AND released)'),
    sa.CheckConstraint('returned_at IS NULL OR (received_by IS NOT NULL AND return_condition IS NOT NULL)'),
    sa.CheckConstraint('start_at < due_at'),
    sa.ForeignKeyConstraint(['handed_by'], ['login_account.user_id'], ),
    sa.ForeignKeyConstraint(['item_id', 'type_id'], ['borrow_item.id', 'borrow_item.type_id'], ),
    sa.ForeignKeyConstraint(['received_by'], ['login_account.user_id'], ),
    sa.ForeignKeyConstraint(['unit_id', 'type_id'], ['equipment_unit.id', 'equipment_unit.type_id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_equipment_reservation_handed_by'), 'equipment_reservation', ['handed_by'], unique=False)
    op.create_index(op.f('ix_equipment_reservation_item_id'), 'equipment_reservation', ['item_id'], unique=False)
    op.create_index(op.f('ix_equipment_reservation_received_by'), 'equipment_reservation', ['received_by'], unique=False)
    op.create_index(op.f('ix_equipment_reservation_type_id'), 'equipment_reservation', ['type_id'], unique=False)
    op.create_index(op.f('ix_equipment_reservation_unit_id'), 'equipment_reservation', ['unit_id'], unique=False)
    op.add_column('notification', sa.Column('equipment_event_id', sa.BigInteger(), nullable=True))
    op.create_index(op.f('ix_notification_equipment_event_id'), 'notification', ['equipment_event_id'], unique=False)
    op.create_unique_constraint('uq_notification_equipment', 'notification', ['recipient_id', 'equipment_event_id'])
    op.create_foreign_key('fk_notification_equipment', 'notification', 'equipment_event', ['equipment_event_id'], ['id'])
    op.drop_constraint('ck_notification_source', 'notification', type_='check')
    op.create_check_constraint('ck_notification_source', 'notification', 'num_nonnulls(appointment_event_id, room_event_id, equipment_event_id) = 1')


def downgrade():
    op.execute("DELETE FROM notification WHERE equipment_event_id IS NOT NULL")
    op.drop_constraint('ck_notification_source', 'notification', type_='check')
    op.create_check_constraint('ck_notification_source', 'notification', 'num_nonnulls(appointment_event_id, room_event_id) = 1')
    op.drop_constraint('fk_notification_equipment', 'notification', type_='foreignkey')
    op.drop_constraint('uq_notification_equipment', 'notification', type_='unique')
    op.drop_index(op.f('ix_notification_equipment_event_id'), table_name='notification')
    op.drop_column('notification', 'equipment_event_id')
    op.drop_index(op.f('ix_equipment_reservation_unit_id'), table_name='equipment_reservation')
    op.drop_index(op.f('ix_equipment_reservation_type_id'), table_name='equipment_reservation')
    op.drop_index(op.f('ix_equipment_reservation_received_by'), table_name='equipment_reservation')
    op.drop_index(op.f('ix_equipment_reservation_item_id'), table_name='equipment_reservation')
    op.drop_index(op.f('ix_equipment_reservation_handed_by'), table_name='equipment_reservation')
    op.drop_table('equipment_reservation')
    op.drop_index(op.f('ix_equipment_event_unit_id'), table_name='equipment_event')
    op.drop_index(op.f('ix_equipment_event_request_id'), table_name='equipment_event')
    op.drop_index(op.f('ix_equipment_event_faculty_id'), table_name='equipment_event')
    op.drop_index(op.f('ix_equipment_event_actor_id'), table_name='equipment_event')
    op.drop_table('equipment_event')
    op.drop_index(op.f('ix_equipment_custodian_user_id'), table_name='equipment_custodian')
    op.drop_table('equipment_custodian')
    op.drop_index(op.f('ix_borrow_item_type_id'), table_name='borrow_item')
    op.drop_index(op.f('ix_borrow_item_request_id'), table_name='borrow_item')
    op.drop_index(op.f('ix_borrow_item_faculty_id'), table_name='borrow_item')
    op.drop_table('borrow_item')
    op.drop_index('uq_pending_borrow_extension', table_name='borrow_extension', postgresql_where="status = 'Pending'")
    op.drop_index(op.f('ix_borrow_extension_request_id'), table_name='borrow_extension')
    op.drop_index(op.f('ix_borrow_extension_decided_by'), table_name='borrow_extension')
    op.drop_table('borrow_extension')
    op.drop_index(op.f('ix_equipment_unit_type_id'), table_name='equipment_unit')
    op.drop_table('equipment_unit')
    op.drop_index(op.f('ix_borrow_request_borrower_id'), table_name='borrow_request')
    op.drop_index('ix_borrow_faculty_status', table_name='borrow_request')
    op.drop_table('borrow_request')
    op.drop_index(op.f('ix_equipment_type_faculty_id'), table_name='equipment_type')
    op.drop_index(op.f('ix_equipment_type_category_id'), table_name='equipment_type')
    op.drop_table('equipment_type')
    op.drop_table('equipment_category')
