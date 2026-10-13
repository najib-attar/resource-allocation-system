"""Trusted provisioning, password verification and revocable user identity."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import secrets

from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from .persistence.models import LoginAccount, Role, User
from .persistence.repository import PersistenceError


DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32), method="scrypt")


@dataclass(frozen=True)
class Principal:
    user_id: int
    name: str
    role: str
    administrator: bool
    session_version: int


class AccountService:
    def __init__(self, database):
        self.database = database

    def provision(self, user_id, username, password, administrator=False, reset=False):
        username = username.strip().casefold() if isinstance(username, str) else ""
        if not re.fullmatch(r"[a-z0-9_.-]{3,100}", username):
            raise PersistenceError("Username must contain 3-100 letters, digits, dots, hyphens or underscores.")
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise PersistenceError("Use a password of 12-256 characters.")
        password_hash = generate_password_hash(password, method="scrypt")
        with self.database.transaction() as session:
            user = session.get(User, user_id)
            if user is None:
                raise PersistenceError("Provision an account only for an existing university user.")
            account = session.get(LoginAccount, user_id, with_for_update=True)
            if account is None and reset:
                raise PersistenceError("No account exists to reset. Provision it without the reset option first.")
            if account is not None and not reset:
                raise PersistenceError("An account already exists; password replacement requires an explicit reset.")
            if account is None:
                account = LoginAccount(user_id=user_id, username=username)
                session.add(account)
            account.username, account.password_hash = username, password_hash
            account.enabled, account.administrator = True, bool(administrator)
            account.failed_attempts, account.locked_until = 0, None
            if reset:
                account.session_version += 1

    def _principal(self, session, account):
        user = session.get(User, account.user_id)
        if not account.enabled or user is None or user.status.casefold() != "active":
            return None
        role = session.get(Role, user.primary_role_id)
        return Principal(user.id, user.name, role.name,
                         account.administrator or role.name == "Administrator", account.session_version)

    def authenticate(self, username, password):
        username = username.strip().casefold() if isinstance(username, str) else ""
        if not isinstance(password, str) or len(password) > 256:
            return None
        now = datetime.now(timezone.utc)
        with self.database.transaction() as session:
            account = session.scalar(select(LoginAccount).where(LoginAccount.username == username).with_for_update())
            if account is None:
                check_password_hash(DUMMY_HASH, password)
                return None
            if account.locked_until is not None and account.locked_until > now:
                return None
            if not check_password_hash(account.password_hash, password):
                account.failed_attempts += 1
                if account.failed_attempts >= 5:
                    account.locked_until = now + timedelta(minutes=5)
                    account.failed_attempts = 0
                return None
            account.failed_attempts, account.locked_until = 0, None
            return self._principal(session, account)

    def identity(self, user_id, version):
        if type(user_id) is not int or type(version) is not int:
            return None
        with self.database.transaction(read_only=True) as session:
            account = session.get(LoginAccount, user_id)
            if account is None or account.session_version != version:
                return None
            return self._principal(session, account)

    def revoke(self, user_id):
        with self.database.transaction() as session:
            account = session.get(LoginAccount, user_id, with_for_update=True)
            if account is not None:
                account.session_version += 1
