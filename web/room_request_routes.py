"""Authenticated room forms and presentation; no scheduling or SQL in routes."""

from datetime import date, datetime, timezone
from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, url_for
from .calendar_service import CalendarError, local_instant, university_zone
from .room_request_service import RoomRequestService, RoomRequestError


def create_room_blueprint(database_provider, gateway_provider, strategy_provider):
    blueprint = Blueprint('rooms', __name__, url_prefix='/rooms')

    def service():
        return RoomRequestService(database_provider(),gateway_provider(),strategy_provider())

    def actor():
        return g.principal.user_id

    def student():
        if g.principal.role != 'Student':
            abort(403,description='Only students may organize room requests.')
        return actor()

    def integer(value):
        try:
            parsed=int(value)
            if not 1 <= parsed <= 2147483647:
                raise ValueError()
            return parsed
        except (TypeError,ValueError) as error:
            raise RoomRequestError('Enter valid positive identifiers, duration and attendee count.') from error

    def invitees():
        return [integer(x) for x in request.form.getlist('professorIds')]

    def fields():
        return {'category':request.form.get('category'),'purpose':request.form.get('purpose',''),
                'description':request.form.get('description',''),'club':request.form.get('club',''),
                'count':integer(request.form.get('count')),'duration':integer(request.form.get('duration')),
                'start':local_instant(request.form.get('start')),'features':request.form.getlist('features'),
                'faculty':integer(request.form['faculty']) if request.form.get('faculty') else None,
                'building':request.form.get('building','')}

    @blueprint.errorhandler(PermissionError)
    def unauthorized(error):
        if request.endpoint == 'rooms.candidates':
            return jsonify(error=str(error)),403
        return render_template('appointment_error.html',message=str(error)),403

    @blueprint.errorhandler(CalendarError)
    def invalid(error):
        if request.endpoint == 'rooms.candidates':
            return jsonify(error=str(error)),409
        return render_template('appointment_error.html',message=str(error)),409

    @blueprint.get('/')
    def index():
        return render_template('room_requests.html',items=service().list_for(actor()),zone=university_zone().key)

    @blueprint.get('/availability/<int:room_id>')
    def availability(room_id):
        try:
            day=date.fromisoformat(request.args.get('date',datetime.now(university_zone()).date().isoformat()))
        except (ValueError,TypeError) as error:
            raise RoomRequestError('Choose a valid room-calendar date.') from error
        return render_template('room_availability.html',calendar=service().availability(actor(),room_id,day))

    @blueprint.route('/new',methods=['GET','POST'])
    def new():
        student()
        if request.method == 'POST':
            key=service().submit(actor(),fields(),invitees(),integer(request.form.get('roomId')))
            return redirect(url_for('rooms.detail',request_id=key))
        return render_template('room_request_new.html',directory=service().directory(actor()),item=None,
                               today=datetime.now(university_zone()).strftime('%Y-%m-%d'),zone=university_zone().key)

    @blueprint.post('/candidates')
    def candidates():
        student()
        result=service().recommend(actor(),fields(),invitees())
        for group in ('candidates','alternatives'):
            for row in result[group]:
                row['localStart']=datetime.fromtimestamp(row['start'],timezone.utc).astimezone(university_zone()).strftime('%Y-%m-%dT%H:%M')
                row['localEnd']=datetime.fromtimestamp(row['end'],timezone.utc).astimezone(university_zone()).strftime('%Y-%m-%dT%H:%M')
        return jsonify(result)

    @blueprint.get('/<int:request_id>')
    def detail(request_id):
        item=service().detail(request_id,actor())
        return render_template('room_request_detail.html',item=item,zone=university_zone().key,
                               calendar_date=item['start'].astimezone(university_zone()).date().isoformat())

    @blueprint.route('/<int:request_id>/revise',methods=['GET','POST'])
    def revise(request_id):
        student()
        item=service().detail(request_id,actor())
        if item['organizerId'] != actor() or item['status'] not in {'Pending Faculty Approval','Needs Revision','Rejected'}:
            raise RoomRequestError('Only a pending organizer request may be revised. Cancel confirmed events and create a new request.')
        if request.method == 'POST':
            service().submit(actor(),fields(),invitees(),integer(request.form.get('roomId')),request_id,integer(request.form.get('revision')))
            return redirect(url_for('rooms.detail',request_id=request_id))
        return render_template('room_request_new.html',directory=service().directory(actor()),item=item,
                               today=datetime.now(university_zone()).strftime('%Y-%m-%d'),zone=university_zone().key)

    @blueprint.post('/<int:request_id>/decision')
    def decision(request_id):
        value=request.form.get('decision')
        if value not in {'approve','reject'}:
            raise RoomRequestError('Choose approve or reject.')
        service().decide(request_id,actor(),integer(request.form.get('revision')),value == 'approve',request.form.get('reason',''))
        return redirect(url_for('rooms.detail',request_id=request_id))

    @blueprint.post('/<int:request_id>/cancel')
    def cancel(request_id):
        service().cancel(request_id,actor(),integer(request.form.get('revision')))
        return redirect(url_for('rooms.detail',request_id=request_id))

    @blueprint.post('/<int:request_id>/invitation')
    def invitation(request_id):
        value=request.form.get('response')
        if value not in {'accept','decline'}:
            raise RoomRequestError('Choose accept or decline.')
        service().respond(request_id,actor(),integer(request.form.get('revision')),value == 'accept')
        return redirect(url_for('rooms.detail',request_id=request_id))

    @blueprint.route('/configuration',methods=['GET','POST'])
    def configuration():
        directory=service().directory(actor(),configuration=True)
        if request.method == 'POST':
            action=request.form.get('action')
            if action == 'approver':
                service().configure_approver(actor(),integer(request.form.get('faculty')),integer(request.form.get('approver')))
            elif action == 'policy':
                try:
                    whitelist=[integer(x.strip()) for x in request.form.get('allowedUsers','').split(',') if x.strip()]
                except AttributeError as error:
                    raise RoomRequestError('Enter a comma-separated whitelist of university identifiers.') from error
                service().configure_room(actor(),integer(request.form.get('roomId')),integer(request.form.get('faculty')),
                    request.form.get('enabled') == 'yes',request.form.getlist('categories'),request.form.get('restricted') == 'yes',whitelist)
            elif action == 'close':
                service().close_room(actor(),integer(request.form.get('roomId')),local_instant(request.form.get('start')),
                                     local_instant(request.form.get('end')),request.form.get('reason',''))
            elif action == 'reopen':
                service().reopen_room(actor(),integer(request.form.get('closureId')))
            else:
                raise RoomRequestError('Choose a supported room configuration action.')
            return redirect(url_for('rooms.configuration'))
        return render_template('room_configuration.html',directory=directory,zone=university_zone().key)

    return blueprint
