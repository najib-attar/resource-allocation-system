"""Explicit authenticated test clients; production auth and CSRF remain enabled."""

import secrets
from unittest import mock

from web.account_service import Principal

TEST_SECRET = "isolated-test-session-key-not-for-production-use"


class AuthenticatedClient:
    def __init__(self, app, user_id=2, version=1):
        self.client = app.test_client()
        self.csrf = secrets.token_urlsafe(32)
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["session_version"] = version
            session["csrf"] = self.csrf

    def post(self, *args, **kwargs):
        kwargs["headers"] = dict(kwargs.get("headers", {})) | {"X-CSRF-Token": self.csrf}
        return self.client.post(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.client, name)


def authorized_client(app, user_id=2, version=1):
    app.config["SECRET_KEY"] = TEST_SECRET
    return AuthenticatedClient(app, user_id, version)


def mocked_administrator():
    return mock.patch("web.security.AccountService.identity", return_value=Principal(2, "Fixture administrator", "Instructor", True, 1))
