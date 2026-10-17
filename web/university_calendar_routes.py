"""Authenticated calendar presentation; source workflows retain their own permissions."""
from flask import Blueprint, g, redirect, render_template, request, url_for

from .calendar_service import CalendarError
from .university_calendar import UniversityCalendarService


def create_calendar_blueprint(database_provider):
    blueprint = Blueprint('calendar', __name__, url_prefix='/calendar')

    def service():
        return UniversityCalendarService(database_provider())

    @blueprint.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @blueprint.errorhandler(CalendarError)
    def invalid(error):
        return render_template('calendar_error.html', message=str(error)), 400

    @blueprint.errorhandler(PermissionError)
    def forbidden(error):
        return render_template('calendar_error.html', message=str(error)), 403

    @blueprint.get('/')
    def index():
        filtered = request.args.get('filtered') == '1'
        values = service().load(g.principal.user_id, request.args.get('view', 'month'), request.args.get('date'),
            request.args.getlist('category') if filtered else None,
            request.args.getlist('state') if filtered else None, request.args.get('scope', 'relevant'))

        def link(view=None, day=None):
            return url_for('calendar.index', view=view or values['view'], date=day or values['date'],
                filtered='1', category=sorted(values['categories']), state=sorted(values['states']), scope=values['scope'])

        return render_template('university_calendar.html', calendar=values, calendar_link=link)

    @blueprint.get('/academic/<int:request_id>')
    def academic(request_id):
        return render_template('calendar_academic_detail.html',
            item=service().academic_detail(g.principal.user_id, request_id, request.args.get('date')))

    @blueprint.route('/publications', methods=['GET', 'POST'])
    def publications():
        if request.method == 'POST':
            try:
                key = int(request.form.get('id', ''))
                instructor = int(request.form['instructor']) if request.form.get('instructor') else None
                if key <= 0 or request.form.get('visibility') not in {'private', 'published'}:
                    raise ValueError()
            except ValueError as error:
                raise CalendarError('Select an activity, visibility and optional professor.') from error
            service().publish(g.principal.user_id, key, request.form['visibility'] == 'published', instructor)
            return redirect(url_for('calendar.publications'))
        return render_template('calendar_publications.html', values=service().publications(g.principal.user_id))

    return blueprint
