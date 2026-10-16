"""Leading composite FK indexes and physical-release integrity."""
from alembic import op

revision = '0044c'
down_revision = '0044b'
branch_labels = None
depends_on = None


INDEXES = (
    ('borrow_item', 'request_id', 'faculty_id', 'ix_borrow_item_request_faculty'),
    ('borrow_item', 'type_id', 'faculty_id', 'ix_borrow_item_type_faculty'),
    ('equipment_reservation', 'item_id', 'type_id', 'ix_equipment_reservation_item_type'),
    ('equipment_reservation', 'unit_id', 'type_id', 'ix_equipment_reservation_unit_type'),
)


def upgrade():
    for table, leading, other, name in INDEXES:
        op.create_index(name, table, [leading, other])
        op.drop_index('ix_'+table+'_'+leading, table_name=table)
    op.create_check_constraint('ck_equipment_physical_release', 'equipment_reservation',
                               'NOT released OR handed_at IS NULL OR returned_at IS NOT NULL')


def downgrade():
    op.drop_constraint('ck_equipment_physical_release', 'equipment_reservation', type_='check')
    for table, leading, other, name in reversed(INDEXES):
        op.create_index('ix_'+table+'_'+leading, table, [leading])
        op.drop_index(name, table_name=table)
