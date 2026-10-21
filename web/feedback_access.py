"""Current resource responsibility, shared by private reports and their inbox."""
from sqlalchemy import and_, func, or_, select
from .equipment_access import custodian_faculties
from .persistence.models import FacultyRoomApprover, LoginAccount, ResourceFeedback, Role, User


def room_faculties(actor):
    return select(FacultyRoomApprover.faculty_id).join(User, User.id == FacultyRoomApprover.user_id).join(
        LoginAccount, LoginAccount.user_id == User.id).join(Role, Role.id == User.primary_role_id).where(
        FacultyRoomApprover.user_id == actor, func.lower(User.status) == 'active', LoginAccount.enabled.is_(True),
        Role.name != 'Student', or_(Role.name.in_(['Staff', 'Administrator']), LoginAccount.administrator.is_(True)))


def managed_scope(actor):
    return or_(and_(ResourceFeedback.room_request_id.is_not(None), ResourceFeedback.faculty_id.in_(room_faculties(actor))),
               and_(ResourceFeedback.equipment_reservation_id.is_not(None), ResourceFeedback.faculty_id.in_(custodian_faculties(actor))))


def visible_scope(actor):
    return or_(ResourceFeedback.reporter_id == actor, managed_scope(actor))
