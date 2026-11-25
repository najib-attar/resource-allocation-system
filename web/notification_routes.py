"""Authenticated notification presentation; identity always comes from the session."""

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for
from .notification_service import INBOX_KINDS, INBOX_READ_STATES, NotificationService


def add_notification_urls(inbox):
    destinations = {
        'appointment': ('appointments.detail', 'appointment_id'),
        'room': ('rooms.detail', 'request_id'),
        'equipment': ('equipment.detail', 'request_id'),
        'feedback': ('feedback.detail', 'report_id'),
        'eligibility': ('professor.page', 'request_id'),
    }
    for item in inbox['items']:
        endpoint, parameter = destinations[item['kind']]
        arguments = {parameter: item['subject_id']}
        if item['kind'] == 'eligibility':
            arguments['_anchor'] = f"eligibility-review-{item['review_version']}"
        item['url'] = url_for(endpoint, **arguments)
    return inbox


def create_notification_blueprint(database_provider):
    blueprint = Blueprint('notifications', __name__, url_prefix='/notifications')

    def inbox(limit=20):
        return add_notification_urls(NotificationService(database_provider()).inbox(g.principal.user_id, limit))

    @blueprint.errorhandler(PermissionError)
    def private(error):
        return jsonify(error=str(error)), 403

    @blueprint.errorhandler(ValueError)
    def invalid(error):
        if request.endpoint == 'notifications.index':
            return render_template('workspace_error.html', status=400, message=str(error),
                recovery=('notifications.index', 'Inbox')), 400, {'Cache-Control': 'no-store'}
        return jsonify(error=str(error)), 400

    @blueprint.get('/')
    def index():
        raw = request.args.get('before')
        try:
            before = int(raw) if raw is not None else None
        except ValueError as error:
            raise ValueError('This page of Inbox history is unavailable.') from error
        service = NotificationService(database_provider())
        result = add_notification_urls(service.inbox_page(g.principal.user_id,
            kind=request.args.get('kind', 'all'), read_state=request.args.get('state', 'all'), before=before))
        return render_template('notifications.html', inbox=result, kinds=INBOX_KINDS,
            read_states=INBOX_READ_STATES), 200, {'Cache-Control': 'no-store'}

    @blueprint.get('/feed')
    def feed():
        result = inbox()
        response = jsonify(html=render_template('components/_notification_items.html', inbox=result),
                           unreadCount=result['unreadCount'], throughId=result['throughId'])
        response.headers['Cache-Control'] = 'no-store'
        return response

    @blueprint.post('/read')
    def read():
        raw = request.form.get('id') if 'id' in request.form else request.form.get('throughId')
        try:
            key = int(raw)
        except (TypeError, ValueError) as error:
            raise ValueError('Invalid notification identifier.') from error
        service = NotificationService(database_provider())
        filters = {}
        if 'id' in request.form:
            service.mark_read(g.principal.user_id, notification_id=key)
        else:
            filters = {name: request.form[name] for name in ('kind', 'state') if name in request.form}
            service.mark_read(g.principal.user_id, through_id=key,
                kind=filters.get('kind', 'all'), read_state=filters.get('state', 'all'))
        if request.headers.get('Accept') == 'application/json':
            return jsonify(status='success')
        return redirect(url_for('notifications.index', **filters))

    return blueprint
