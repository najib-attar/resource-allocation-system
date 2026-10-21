"""Shared feedback screens; services own permissions and state."""
import uuid
from flask import Blueprint, g, redirect, render_template, request, url_for
from .calendar_service import CalendarError
from .feedback_service import FeedbackError, FeedbackService
from .persistence.models import FEEDBACK_CATEGORIES, FEEDBACK_PRIORITIES, FEEDBACK_STATES


def create_feedback_blueprint(database_provider):
    blueprint = Blueprint('feedback', __name__, url_prefix='/feedback')

    def service():
        return FeedbackService(database_provider())

    @blueprint.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def integer(value):
        try:
            result = int(value)
            if not 1 <= result <= 9223372036854775807:
                raise ValueError()
            return result
        except (TypeError, ValueError) as error:
            raise FeedbackError('Select valid resource and revision identifiers.') from error

    @blueprint.errorhandler(PermissionError)
    def forbidden(error):
        return render_template('appointment_error.html', message=str(error)), 403

    @blueprint.errorhandler(CalendarError)
    def invalid(error):
        return render_template('appointment_error.html', message=str(error)), 409

    @blueprint.get('/')
    def index():
        current, actor = service(), g.principal.user_id
        managed = current.can_manage(actor)
        scope = request.args.get('scope', 'managed' if managed else 'mine')
        filters = {key:request.args.get(key, '') for key in ('status','category','kind','resource')}
        all_items = current.list_for(actor, scope)
        return render_template('feedback_list.html', items=current.list_for(actor, scope, **filters),
            resources={item['resourceKey']:item['resource'] for item in all_items}, filters=filters, scope=scope,
            managed=managed, states=FEEDBACK_STATES, categories=FEEDBACK_CATEGORIES), 200, {'Cache-Control':'private, no-store'}

    @blueprint.route('/new/<kind>/<int:booking_id>', methods=['GET','POST'])
    def new(kind, booking_id):
        current, actor = service(), g.principal.user_id
        context = current.context(kind, booking_id, actor)
        if request.method == 'POST':
            key = current.submit(actor, kind, booking_id, integer(request.form.get('resourceId')),
                request.form.get('category'), request.form.get('description'), request.form.get('urgent') == 'yes',
                request.form.get('submission_key'))
            return redirect(url_for('feedback.detail', report_id=key))
        return render_template('feedback_new.html', context=context, submission_key=uuid.uuid4().hex)

    @blueprint.get('/<int:report_id>')
    def detail(report_id):
        return render_template('feedback_detail.html', item=service().detail(report_id, g.principal.user_id),
            action_key=uuid.uuid4().hex, states=FEEDBACK_STATES, priorities=FEEDBACK_PRIORITIES), 200, {'Cache-Control':'private, no-store'}

    @blueprint.post('/<int:report_id>/update')
    def update(report_id):
        action = request.form.get('action')
        if action not in {'review','reply'}:
            raise FeedbackError('Choose staff review or reporter clarification.')
        service().update(report_id, g.principal.user_id, integer(request.form.get('revision')),
            request.form.get('status'), request.form.get('priority'), request.form.get('response'),
            request.form.get('action_key'), reply=action == 'reply')
        return redirect(url_for('feedback.detail', report_id=report_id))

    return blueprint
