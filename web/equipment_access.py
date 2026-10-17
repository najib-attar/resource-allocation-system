"""Shared current-custodian scope for workflows, notifications and calendars."""
from sqlalchemy import func, or_, select
from .persistence.models import EquipmentCustodian, LoginAccount, Role, User


def valid_custodians():
    return select(EquipmentCustodian.faculty_id, EquipmentCustodian.user_id).join(
        User, User.id == EquipmentCustodian.user_id).join(LoginAccount, LoginAccount.user_id == User.id).join(
        Role, Role.id == User.primary_role_id).where(func.lower(User.status) == 'active', LoginAccount.enabled.is_(True),
        or_(LoginAccount.administrator.is_(True), Role.name.in_(['Staff', 'Administrator'])))


def custodian_faculties(actor):
    return valid_custodians().where(EquipmentCustodian.user_id == actor).with_only_columns(EquipmentCustodian.faculty_id)
