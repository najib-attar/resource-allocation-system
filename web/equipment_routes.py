"""Equipment forms and shared-layout presentation; services enforce authority."""
from datetime import datetime, timedelta, timezone
import json
import uuid

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for
from .calendar_service import CalendarError, local_instant, university_zone
from .equipment_service import EquipmentError, EquipmentService


def create_equipment_blueprint(database_provider, gateway_provider):
    blueprint = Blueprint('equipment', __name__, url_prefix='/equipment')

    def service():
        return EquipmentService(database_provider(), gateway_provider())

    def actor():
        return g.principal.user_id

    def integer(value):
        try:
            number = int(value)
            if not 1 <= number <= 2147483647:
                raise ValueError()
            return number
        except (ValueError, TypeError) as error:
            raise EquipmentError('Enter positive identifiers and quantities.') from error

    def specifications(value):
        try:
            return json.loads(value or '{}')
        except (ValueError, TypeError) as error:
            raise EquipmentError('Specifications must be a valid JSON object of text values.') from error

    @blueprint.errorhandler(PermissionError)
    def forbidden(error):
        return render_template('equipment_error.html', message=str(error)), 403

    @blueprint.errorhandler(CalendarError)
    def invalid(error):
        return render_template('equipment_error.html', message=str(error)), 409

    @blueprint.get('/')
    def index():
        service().refresh_overdue_alerts(actor())
        return render_template('equipment_requests.html', items=service().list_for(actor()), directory=service().directory(actor()))

    @blueprint.route('/catalog', methods=['GET', 'POST'])
    def catalog():
        source = request.form if request.method == 'POST' else request.args
        default_start = (datetime.now(university_zone())+timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        start_text = source.get('start', default_start.strftime('%Y-%m-%dT%H:%M'))
        due_text = source.get('due', (default_start+timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'))
        start, due = local_instant(start_text), local_instant(due_text)
        rows = service().catalog(actor(), start, due)
        result = None
        if request.method == 'POST':
            items = [{'typeId': integer(key[4:]), 'quantity': integer(value),
                      'specifications': specifications(source.get('spec_'+key[4:], '{}'))}
                     for key, value in source.items() if key.startswith('qty_') and value not in {'', '0'}]
            faculty = integer(source.get('faculty'))
            if source.get('action') == 'recommend':
                result = service().recommend(actor(), faculty, items, start, due)
                for period in result['alternativePeriods']:
                    period['startAt'] = datetime.fromtimestamp(period['start'], timezone.utc)
                    period['endAt'] = datetime.fromtimestamp(period['end'], timezone.utc)
            elif source.get('action') == 'submit':
                key = service().submit(actor(), faculty, items, start, due, source.get('purpose', ''), source.get('notes', ''), source.get('submission_key'))
                return redirect(url_for('equipment.detail', request_id=key))
            else:
                raise EquipmentError('Choose check availability or submit.')
        return render_template('equipment_catalog.html', items=rows, directory=service().directory(actor()),
            start=start_text, due=due_text, zone=university_zone().key, result=result,
            submission_key=source.get('submission_key') or uuid.uuid4().hex)

    @blueprint.get('/<int:request_id>')
    def detail(request_id):
        return render_template('equipment_detail.html', item=service().detail(actor(), request_id))

    @blueprint.post('/<int:request_id>/<action>')
    def transition(request_id, action):
        current = service()
        if action == 'approve':
            current.decide(actor(), request_id, True, request.form.get('reason', ''))
        elif action == 'reject':
            current.decide(actor(), request_id, False, request.form.get('reason', ''))
        elif action == 'cancel':
            current.cancel(actor(), request_id)
        elif action == 'handover':
            current.handover(actor(), request_id, request.form.get('condition', ''))
        elif action == 'intend-return':
            current.intend_return(actor(), request_id)
        elif action == 'return':
            current.return_units(actor(), request_id, [integer(v) for v in request.form.getlist('unitIds')],
                request.form.get('condition'), request.form.get('notes', ''))
        elif action == 'extension':
            current.request_extension(actor(), request_id, local_instant(request.form.get('due')), request.form.get('reason', ''))
        elif action in {'approve-extension', 'reject-extension'}:
            current.decide_extension(actor(), request_id, integer(request.form.get('extensionId')), action == 'approve-extension')
        else:
            return jsonify(error='Unknown borrowing operation.'), 404
        return redirect(url_for('equipment.detail', request_id=request_id))

    @blueprint.route('/inventory/<int:faculty_id>', methods=['GET', 'POST'])
    def inventory(faculty_id):
        current = service()
        # This read verifies current custodian authority even for malformed POST actions.
        current.inventory(actor(), faculty_id)
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'type':
                current.create_type(actor(), faculty_id, request.form.get('category'), request.form.get('name'),
                    request.form.get('description', ''), specifications(request.form.get('specifications')),
                    integer(request.form.get('max_days')), request.form.get('pickup', ''),
                    [integer(x) for x in request.form.getlist('eligible_faculties')])
            elif action == 'unit':
                current.add_unit(actor(), integer(request.form.get('type_id')), request.form.get('asset_tag'), request.form.get('condition', 'usable'))
            elif action == 'condition':
                current.set_condition(actor(), integer(request.form.get('unit_id')), request.form.get('condition'), request.form.get('notes', ''))
            elif action == 'policy':
                current.configure_type(actor(), integer(request.form.get('type_id')), request.form.get('enabled') == 'on', integer(request.form.get('max_days')))
            else:
                raise EquipmentError('Choose an inventory operation.')
            return redirect(url_for('equipment.inventory', faculty_id=faculty_id))
        return render_template('equipment_inventory.html', inventory=current.inventory(actor(), faculty_id),
                               faculty_id=faculty_id, directory=current.directory(actor()))

    @blueprint.route('/custodians', methods=['GET', 'POST'])
    def custodians():
        accounts = service().management_directory(actor())
        if request.method == 'POST':
            service().assign_custodian(actor(), integer(request.form.get('faculty')), integer(request.form.get('custodian')))
            return redirect(url_for('equipment.custodians'))
        return render_template('equipment_custodians.html', directory=service().directory(actor()), accounts=accounts)

    return blueprint
