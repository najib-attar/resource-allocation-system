"""Signed, revocable application sessions and CSRF; no client-assigned identity."""

from datetime import timedelta
import hmac
import os
import secrets

from flask import abort, g, redirect, render_template, request, session, url_for

from .account_service import AccountService


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def home_endpoint(principal):
    if principal.administrator:
        return "index"
    return "student.home" if principal.role == "Student" else "appointments.index"


def init_security(app, database_provider):
    app.config.update(SECRET_KEY=os.environ.get("RESOURCE_ALLOCATION_SECRET_KEY"),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.environ.get("RESOURCE_ALLOCATION_SECURE_COOKIE", "0") == "1",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def authenticate_request():
        if request.endpoint == "static":
            return None
        secret = app.config.get("SECRET_KEY")
        if not isinstance(secret, str) or len(secret) < 32:
            return "Configure RESOURCE_ALLOCATION_SECRET_KEY with at least 32 random characters before serving authenticated workflows.", 503
        g.principal = None
        if "user_id" in session:
            g.principal = AccountService(database_provider()).identity(session.get("user_id"), session.get("session_version"))
            if g.principal is None:
                session.clear()
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
            if not isinstance(supplied, str) or not hmac.compare_digest(session.get("csrf", ""), supplied) or not supplied:
                abort(400, description="Missing or invalid CSRF token. Refresh the form and retry.")
        if request.endpoint == "login":
            return None
        if g.principal is None:
            return redirect(url_for("login", next=request.path))
        if request.endpoint and request.endpoint.startswith("student."):
            if g.principal.role != "Student":
                abort(403, description="Student access required.")
            return None
        if request.endpoint and request.endpoint.startswith("appointments."):
            return None
        if request.endpoint and request.endpoint.startswith("rooms."):
            return None
        if request.endpoint and request.endpoint.startswith("notifications."):
            return None
        if request.endpoint and request.endpoint.startswith("equipment."):
            return None
        if request.endpoint and request.endpoint.startswith("calendar."):
            return None
        if request.endpoint and request.endpoint.startswith("waiting."):
            return None
        if request.endpoint == "logout":
            return None
        if not g.principal.administrator:
            if request.endpoint == "index":
                return redirect(url_for(home_endpoint(g.principal)))
            abort(403, description="University administration access required. Your own calendar is available in Appointments.")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            principal = AccountService(database_provider()).authenticate(request.form.get("username"), request.form.get("password"))
            if principal is None:
                error = "Sign-in failed. Check your credentials or retry later if temporarily locked."
            else:
                session.clear()
                session.permanent = True
                session["user_id"], session["session_version"] = principal.user_id, principal.session_version
                csrf_token()
                target = request.args.get("next", "")
                if not target.startswith("/") or target.startswith("//") or "\\" in target:
                    target = url_for(home_endpoint(principal))
                return redirect(target)
        return render_template("login.html", error=error), 401 if error else 200

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))
