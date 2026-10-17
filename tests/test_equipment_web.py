"""Authenticated equipment routes, CSV-independent views and migration verification."""
from datetime import timedelta
import uuid
from unittest import mock

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

from auth_fixtures import authorized_client
from postgres_fixtures import PostgresTestCase, ROOT
from runtime_file_guard import forbid_runtime_files
from test_appointments import START, seed_appointments
from test_equipment import EquipmentFixture
from web import app as web_app
from web.account_service import AccountService
from web.equipment_service import EquipmentError
from web.persistence.equipment_demo import seed_equipment_demo
from web.persistence.models import EquipmentType, EquipmentUnit


class EquipmentWebTests(EquipmentFixture):
    def setUp(self):
        super().setUp()
        self.configure_web()

    def client(self, actor):
        return authorized_client(web_app.app, actor)

    def post(self, client, path, values):
        with client.session_transaction() as session:
            token = session['csrf']
        return client.post(path, data={'csrf_token':token, **values})

    def test_student_catalog_submit_custodian_approval_handover_and_return(self):
        student, custodian = self.client(1), self.client(6)
        with forbid_runtime_files():
            self.assertEqual(student.get('/equipment/').status_code,200)
            page=student.get('/equipment/catalog?start=2030-01-07T10:00&due=2030-01-10T10:00')
            self.assertEqual(page.status_code,200);self.assertIn(b'Fictional STM32',page.data)
            self.assertNotIn(b'FIC-BOARD-',page.data)
            response=self.post(student,'/equipment/catalog',{'action':'submit','faculty':str(self.faculty),
                'start':'2030-01-07T10:00','due':'2030-01-10T10:00','purpose':'Browser project',
                'submission_key':uuid.uuid4().hex,'qty_'+str(self.type_id):'2'})
            self.assertEqual(response.status_code,302)
            detail=response.location
            self.assertEqual(self.post(custodian,detail+'/approve',{}).status_code,302)
            with mock.patch('web.equipment_service.datetime') as clock:
                clock.now.return_value=START+timedelta(hours=1)
                self.assertEqual(self.post(custodian,detail+'/handover',{'condition':'Verified usable units'}).status_code,302)
            self.assertEqual(self.post(student,detail+'/intend-return',{}).status_code,302)
            with mock.patch('web.equipment_service.datetime') as clock:
                clock.now.return_value=START+timedelta(hours=2)
                self.assertEqual(self.post(custodian,detail+'/return',{'unitIds':[str(u) for u in self.units],'condition':'usable','notes':'Received physically'}).status_code,302)
            self.assertIn(b'Returned',student.get(detail).data)
            self.assertEqual(student.get('/notifications/').status_code,200)

    def test_csrf_and_unauthorized_faculty_actions_are_denied(self):
        key=self.request()
        self.assertEqual(self.client(4).get('/equipment/'+str(key)).status_code,403)
        self.assertEqual(self.client(1).client.post('/equipment/'+str(key)+'/approve').status_code,400)
        self.assertEqual(self.post(self.client(1),'/equipment/'+str(key)+'/approve',{}).status_code,403)
        self.assertEqual(self.client(1).get('/equipment/inventory/'+str(self.faculty)).status_code,403)
        self.assertEqual(self.client(1).get('/equipment/custodians').status_code,403)
        self.assertEqual(self.client(2).get('/equipment/catalog').status_code,403)

    def test_inventory_management_and_recommendations_render_without_ids_in_names(self):
        admin=self.client(6)
        self.assertEqual(admin.get('/equipment/custodians').status_code,200)
        self.assertEqual(admin.get('/equipment/inventory/'+str(self.faculty)).status_code,200)
        student=self.client(1)
        response=self.post(student,'/equipment/catalog',{'action':'recommend','faculty':str(self.faculty),
            'start':'2030-01-07T10:00','due':'2030-01-10T10:00','purpose':'Test', 'qty_'+str(self.type_id):'1'})
        self.assertEqual(response.status_code,200);self.assertIn(b'Your complete request is feasible',response.data)
        self.assertEqual(self.post(admin,'/equipment/inventory/'+str(self.faculty),{'action':'condition','unit_id':self.units[0],
            'condition':'maintenance','notes':'Calibration'}).status_code,302)

    def test_invalid_dates_quantities_and_unknown_operations_fail_safely(self):
        student=self.client(1)
        invalid=student.get('/equipment/catalog?start=broken')
        self.assertEqual(invalid.status_code,409)
        self.assertIn(b'Equipment unavailable',invalid.data)
        self.assertIn(b'Back to equipment',invalid.data)
        self.assertNotIn(b'Back to appointments',invalid.data)
        self.assertEqual(self.post(student,'/equipment/catalog',{'action':'submit','faculty':str(self.faculty),
            'start':'2030-01-07T10:00','due':'2030-01-10T10:00','qty_'+str(self.type_id):'-1'}).status_code,409)
        self.assertEqual(self.post(student,'/equipment/999999/approve',{}).status_code,403)


class EquipmentMigrationDemoTests(PostgresTestCase):
    def test_empty_schema_roundtrip_and_drift(self):
        import os
        with mock.patch.dict(os.environ, {'DATABASE_URL':self.url}):
            command.check(Config(str(ROOT/'alembic.ini')))
            command.downgrade(Config(str(ROOT/'alembic.ini')),'0043c')
            self.assertNotIn('equipment_unit',inspect(self.database.engine).get_table_names())
            command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
            command.check(Config(str(ROOT/'alembic.ini')))

    def test_fictional_moderate_and_large_inventory_never_overwrite_existing(self):
        faculty=seed_appointments(self.database)
        AccountService(self.database).provision(6,'demo-equipment-admin','Fictional-demo-password',administrator=True)
        result=seed_equipment_demo(self.database,6,44,'moderate')
        self.assertEqual((result['equipmentTypes'],result['physicalUnits']),(10,40))
        with self.assertRaises(EquipmentError):seed_equipment_demo(self.database,6,44,'large')
        from web.equipment_service import EquipmentService
        from web.engine_gateway import EngineGateway
        AccountService(self.database).provision(1,'demo-equipment-student','Fictional-demo-password')
        with self.database.transaction(read_only=True) as session:
            type_id=session.scalar(select(EquipmentType.id).order_by(EquipmentType.id))
            self.assertTrue(all(u.asset_tag.startswith('FICTIONAL-') for u in session.scalars(select(EquipmentUnit))))
        result=EquipmentService(self.database,EngineGateway(ROOT)).recommend(1,faculty,[{'typeId':type_id,'quantity':2}],START,START+timedelta(days=2))
        self.assertTrue(result['feasible'])

    def test_large_fictional_inventory_matches_real_engine(self):
        seed_appointments(self.database)
        for actor in (1,6):
            AccountService(self.database).provision(actor,'large-equipment-'+str(actor),'Fictional-demo-password',administrator=actor==6)
        result=seed_equipment_demo(self.database,6,44,'large')
        self.assertEqual(result['physicalUnits'],400)
        from web.equipment_service import EquipmentService
        from web.engine_gateway import EngineGateway
        catalog=EquipmentService(self.database,EngineGateway(ROOT)).catalog(1,START,START+timedelta(days=2))
        self.assertEqual(len(catalog),10)
        self.assertTrue(all(item['available']==32 for item in catalog))
