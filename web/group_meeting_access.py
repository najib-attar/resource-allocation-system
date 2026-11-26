"""Shared authenticated boundary for the disposable generalized meeting pilot."""

from contextlib import contextmanager

from flask import abort, request

from .cdmcs_rehearsal import _read


@contextmanager
def group_session(fixture, *, write=False):
    if request.remote_addr != "127.0.0.1":
        abort(403)
    with _read(fixture, write=write) as result:
        if not result[0].info.get("group_meeting_pilot"):
            abort(403)
        yield result
