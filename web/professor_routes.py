"""Owner-scoped academic intake and tracking; independent of appointments."""
import uuid
from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from .persistence.database import DatabaseBusy
from .persistence.repository import PersistenceError, SubmissionConflict
from .professor_service import ProfessorRequestError, ProfessorService
from .input_validation import integer, parse_time_slots
from .engine_gateway import EngineIntegrationError


def create_professor_blueprint(database_provider):
    blueprint = Blueprint('professor', __name__, url_prefix='/professor')

    @blueprint.after_request
    def private(response):
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @blueprint.errorhandler(PermissionError)
    def forbidden(error):
        return jsonify(error=str(error)), 403

    @blueprint.errorhandler(ProfessorRequestError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @blueprint.errorhandler(SubmissionConflict)
    def conflict(error):
        return jsonify(error=str(error)),409

    @blueprint.errorhandler(DatabaseBusy)
    @blueprint.errorhandler(PersistenceError)
    @blueprint.errorhandler(SQLAlchemyError)
    def unavailable(error):
        return jsonify(error='Academic request data is temporarily unavailable.'), 503

    def number(name, default):
        try:
            return int(request.args.get(name, default))
        except (TypeError, ValueError) as error:
            raise ProfessorRequestError('Use integer pagination values.') from error

    @blueprint.get('/academic-requests')
    def academic_requests():
        return jsonify(ProfessorService(database_provider()).list_for(g.principal.user_id,
            request.args.get('type', ''), request.args.get('status', ''),
            number('limit', 50), number('offset', 0)))

    @blueprint.get('/academic-requests/<int:request_id>')
    def academic_request(request_id):
        return jsonify(ProfessorService(database_provider()).detail(g.principal.user_id, request_id))

    def service():
        return ProfessorService(database_provider())

    def form_values():
        if any(name in request.form for name in ('userId','requesterId','reviewerId','eligibilityStatus')):
            raise ProfessorRequestError('Identity and eligibility decisions are assigned by the server.')
        form=request.form
        kind=form.get('requestType','')
        try:
            slots=parse_time_slots(form.get('timeData','') if kind=='Recurring' else
                f"{form.get('day','')}-{form.get('startTime','')}-{form.get('endTime','')}")
            values=dict(type=kind,spaceId=integer(form.get('spaceId'),'resource',1),
                participantCount=integer(form.get('participantCount'),'participant count',1),slots=slots,
                title=form.get('title',''),purpose=form.get('purpose',''),facultyDeclaration=form.get('facultyDeclaration',''),
                requiredFeature=form.get('requiredFeature',''),requiredBuilding=form.get('requiredBuilding',''))
            if kind=='Exam':
                if form.get('canSplitAcrossRooms') not in ('true','false'):
                    raise ProfessorRequestError('Choose whether the examination may split across rooms.')
                values['exam']=dict(courseCode=form.get('courseCode',''),courseName=form.get('courseName',''),
                    examType=form.get('examType',''),canSplitAcrossRooms=form['canSplitAcrossRooms']=='true')
            if kind=='CommitteeMeeting':
                values['participants']=[dict(userId=integer(value,'participant',1),
                    role=form.get('participantRole_'+value,'Participant')) for value in form.getlist('requiredParticipantIds')]
            return values
        except EngineIntegrationError as error:
            raise ProfessorRequestError(str(error)) from error

    @blueprint.post('/academic-requests')
    def submit_api():
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict):raise ProfessorRequestError('Send an academic request JSON object.')
        values=dict(payload)
        key=values.pop('submissionKey',None)
        result=service().submit(g.principal.user_id,values,key)
        return jsonify(service().detail(g.principal.user_id,result)),201

    @blueprint.get('/requests')
    def pages():
        return render_template('professor_requests.html',data=service().list_for(g.principal.user_id,
            request.args.get('type',''),request.args.get('status',''),number('limit',50),number('offset',0)))

    @blueprint.get('/requests/<int:request_id>')
    def page(request_id):
        return render_template('professor_request.html',data=service().detail(g.principal.user_id,request_id))

    @blueprint.route('/requests/new',methods=['GET','POST'])
    @blueprint.route('/requests/<int:request_id>/revise',methods=['GET','POST'])
    def form(request_id=None):
        item=service().detail(g.principal.user_id,request_id)['item'] if request_id else None
        if item and not item['canRevise']:
            raise ProfessorRequestError('Published reservations are read-only. A replacement workflow requires separate approval.')
        values=request.form.to_dict() if request.method=='POST' else {}
        if item and request.method=='GET':
            values['timeData']=';'.join(f"{s['day']}-{s['startMinutes']//60:02d}:{s['startMinutes']%60:02d}-{s['endMinutes']//60:02d}:{s['endMinutes']%60:02d}" for s in item['slots'])
            for person in item['participants']:
                values['participantRole_'+str(person['id'])]=person['declaredRole']
        kind=values.get('requestType',item['type'] if item else request.args.get('type','OneTime'))
        if kind not in {'Exam','OneTime','Recurring','CommitteeMeeting'}:
            raise ProfessorRequestError('Choose a supported academic request type.')
        error=None
        if request.method=='POST':
            try:
                revision=integer(request.form.get('revision'),'revision',1) if item else None
                result=service().submit(g.principal.user_id,form_values(),request.form.get('submissionKey'),request_id,revision)
                return redirect(url_for('professor.page',request_id=result))
            except (ProfessorRequestError,EngineIntegrationError,SubmissionConflict) as failure:
                error=str(failure)
        return render_template('professor_request_form.html',directory=service().directory(g.principal.user_id),
            kind=kind,item=item,values=values,error=error,submission_key=values.get('submissionKey') or uuid.uuid4().hex),400 if error else 200

    return blueprint
