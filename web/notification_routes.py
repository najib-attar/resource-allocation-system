"""Authenticated notification presentation; identity always comes from the session."""

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for
from .notification_service import NotificationService


def create_notification_blueprint(database_provider):
    blueprint = Blueprint('notifications', __name__, url_prefix='/notifications')

    def inbox(limit=20):
        result = NotificationService(database_provider()).inbox(g.principal.user_id, limit)
        for item in result['items']:
            endpoint = {'appointment': 'appointments.detail', 'room': 'rooms.detail', 'equipment': 'equipment.detail', 'feedback':'feedback.detail'}[item['kind']]
            key = 'appointment_id' if item['kind'] == 'appointment' else 'report_id' if item['kind'] == 'feedback' else 'request_id'
            item['url'] = url_for(endpoint, **{key: item['subject_id']})
        return result

    @blueprint.errorhandler(PermissionError)
    def private(error):
        return jsonify(error=str(error)), 403

    @blueprint.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @blueprint.get('/')
    def index():
        return render_template('notifications.html', inbox=inbox(100)), 200, {'Cache-Control': 'no-store'}

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
        service.mark_read(g.principal.user_id, **({'notification_id': key} if 'id' in request.form else {'through_id': key}))
        if request.headers.get('Accept') == 'application/json':
            return jsonify(status='success')
        return redirect(url_for('notifications.index'))

    return blueprint
