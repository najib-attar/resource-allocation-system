"""Shared waiting-list views; reservation decisions stay in existing services."""

from flask import Blueprint, g, redirect, render_template, request, url_for

from .calendar_service import CalendarError
from .waiting_list_service import WaitingListError, WaitingListService


def create_waiting_blueprint(database_provider, gateway_provider, strategy_provider):
    blueprint = Blueprint('waiting', __name__, url_prefix='/waiting-lists')

    def service():
        return WaitingListService(database_provider(), gateway_provider(), strategy_provider())

    @blueprint.errorhandler(PermissionError)
    def forbidden(error):
        return render_template('appointment_error.html', message=str(error)), 403

    @blueprint.errorhandler(CalendarError)
    def invalid(error):
        return render_template('appointment_error.html', message=str(error)), 409

    @blueprint.get('/')
    def index():
        current = service()
        current.refresh_for(g.principal.user_id)
        return render_template('waiting_lists.html', items=current.list_for(g.principal.user_id), policy=current.policy()), 200, {'Cache-Control': 'private, no-store'}

    @blueprint.get('/policy')
    def policy():
        return render_template('waiting_policy.html', policy=service().policy())

    @blueprint.get('/<int:entry_id>')
    def detail(entry_id):
        return render_template('waiting_detail.html', item=service().detail(entry_id, g.principal.user_id)), 200, {'Cache-Control': 'private, no-store'}

    @blueprint.post('/<int:entry_id>/review')
    def review(entry_id):
        decision = request.form.get('decision')
        if decision not in {'approve', 'reject'}:
            raise WaitingListError('Choose pre-approve or reject.')
        service().review(entry_id, g.principal.user_id, decision == 'approve', request.form.get('reason', ''))
        return redirect(url_for('waiting.detail', entry_id=entry_id))

    @blueprint.post('/<int:entry_id>/cancel')
    def cancel(entry_id):
        service().cancel(entry_id, g.principal.user_id)
        return redirect(url_for('waiting.detail', entry_id=entry_id))

    @blueprint.post('/refresh')
    def refresh():
        service().refresh_for(g.principal.user_id)
        return redirect(url_for('waiting.index'))

    @blueprint.route('/configuration', methods=['GET', 'POST'])
    def configuration():
        current = service()
        policy = current.management(g.principal.user_id)
        if request.method == 'POST':
            try:
                minutes = int(request.form.get('noticeMinutes', ''))
            except (ValueError, TypeError) as error:
                raise WaitingListError('Enter an explicit positive minimum advance notice in minutes.') from error
            current.configure_notice(g.principal.user_id, minutes)
            return redirect(url_for('waiting.configuration'))
        return render_template('waiting_configuration.html', policy=policy)

    return blueprint
