"""Administrative read pages; authoritative service routes retain all mutations."""
from flask import Blueprint, g, render_template, request

from .admin_dashboard_service import AdminDashboardService


def create_administration_blueprint(database_provider):
    blueprint = Blueprint('administration', __name__, url_prefix='/administration')

    @blueprint.after_request
    def private(response):
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @blueprint.errorhandler(ValueError)
    def invalid(error):
        return render_template('administration/error.html', message=str(error)), 400

    @blueprint.errorhandler(LookupError)
    def missing(error):
        return render_template('administration/error.html', message=str(error)), 404

    @blueprint.errorhandler(PermissionError)
    def forbidden(error):
        return render_template('administration/error.html', message=str(error)), 403

    @blueprint.get('/')
    def home():
        return render_template('administration/home.html', home=AdminDashboardService(database_provider()).load(
            g.principal.user_id, request.args.get('queue', 'all')))

    @blueprint.get('/runs/<int:run_id>')
    def run(run_id):
        try:
            page = int(request.args.get('page', '1'))
            allocation_page = int(request.args.get('allocation_page', '1'))
        except ValueError as error:
            raise ValueError('Choose a valid history page.') from error
        return render_template('administration/run.html', run=AdminDashboardService(database_provider()).run_detail(
            g.principal.user_id, run_id, page, allocation_page))

    return blueprint
