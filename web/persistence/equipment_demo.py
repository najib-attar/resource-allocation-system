"""Additive fictional inventory seed, only when no equipment catalog exists."""
import random
from sqlalchemy import select
from .models import (EquipmentCategory, EquipmentCustodian, EquipmentEvent, EquipmentType, EquipmentUnit,
                     OrganizationUnit)
from ..equipment_service import EquipmentService, EquipmentError


def seed_equipment_demo(database, administrator, seed=44, size='moderate'):
    if size not in {'moderate', 'large'}:
        raise EquipmentError('Choose moderate or large fictional inventory.')
    rng = random.Random(seed)
    catalog = [('Computers', 'Fictional university laptop', {'memory': '16 GB', 'platform': 'linux'}),
        ('Computers', 'Fictional study tablet', {'screen': '10 inch'}),
        ('Development boards', 'Fictional STM32 kit', {'architecture': 'arm', 'voltage': '3.3 V'}),
        ('Development boards', 'Fictional Arduino kit', {'architecture': 'avr', 'voltage': '5 V'}),
        ('Development boards', 'Fictional Raspberry Pi kit', {'architecture': 'arm', 'platform': 'linux'}),
        ('Instruments', 'Fictional digital multimeter', {'measurement': 'voltage resistance current'}),
        ('Instruments', 'Fictional oscilloscope', {'channels': '2', 'bandwidth': '100 MHz'}),
        ('Sensors', 'Fictional temperature sensor', {'interface': 'i2c', 'voltage': '3.3 V'}),
        ('Accessories', 'Fictional USB-C adapter', {'connector': 'usb-c'}),
        ('Accessories', 'Fictional STM32 compatible cable', {'connector': 'usb-micro', 'data': 'yes'})]
    with database.transaction() as session:
        EquipmentService(database, None)._admin(session, administrator)
        if session.scalar(select(EquipmentType.id).limit(1)) or session.scalar(select(EquipmentCustodian.faculty_id).limit(1)):
            raise EquipmentError('Existing equipment configuration was found. Nothing was overwritten; use inventory administration instead.')
        faculties = list(session.scalars(select(OrganizationUnit).where(OrganizationUnit.unit_type == 'Faculty').order_by(OrganizationUnit.id).with_for_update()))
        if not faculties:
            raise EquipmentError('Configure fictional faculties before seeding equipment.')
        categories = {row.name: row for row in session.scalars(select(EquipmentCategory))}
        for name in sorted({row[0] for row in catalog}):
            if name not in categories:
                categories[name] = EquipmentCategory(name=name)
                session.add(categories[name])
        session.flush()
        count = 0
        for faculty in faculties:
            session.add(EquipmentCustodian(faculty_id=faculty.id, user_id=administrator))
            for index, (category, name, specs) in enumerate(catalog):
                record = EquipmentType(faculty_id=faculty.id, category_id=categories[category].id, name=name,
                    description='Entirely fictional returnable equipment for university project demonstrations.',
                    specifications=specs, max_loan_days=14, pickup_instructions='Collect and return at the fictional faculty equipment desk.', eligible_faculty_ids=[])
                session.add(record)
                session.flush()
                for number in range(4 if size == 'moderate' else 40):
                    condition = 'usable' if number % 10 < 8 else rng.choice(['maintenance', 'damaged'])
                    unit = EquipmentUnit(type_id=record.id, asset_tag=f'FICTIONAL-{faculty.id}-{index+1:02d}-{number+1:03d}', condition=condition)
                    session.add(unit)
                    session.flush()
                    session.add(EquipmentEvent(faculty_id=faculty.id, unit_id=unit.id, actor_id=administrator,
                        message='Fictional development inventory registered; no reservations or approved loans fabricated.'))
                    count += 1
        return {'faculties': len(faculties), 'equipmentTypes': len(faculties)*len(catalog), 'physicalUnits': count, 'seed': seed}
