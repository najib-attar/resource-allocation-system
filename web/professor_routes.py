"""Read-only professor API, independent of appointments and administrator intake."""
from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from .persistence.database import DatabaseBusy
from .persistence.repository import PersistenceError
from .professor_service import ProfessorRequestError, ProfessorService


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

    return blueprint
