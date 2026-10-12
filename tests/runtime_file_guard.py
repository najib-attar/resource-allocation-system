"""Fail if a web workflow touches retired operational CSV/config/result files."""

from contextlib import ExitStack, contextmanager
import builtins
import io
import os
from unittest import mock


@contextmanager
def forbid_runtime_files():
    def guarded_open(original):
        def checked(path, *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)):
                name = os.fsdecode(path).replace("\\", "/").lower()
                if (name.endswith(".csv") or name.rsplit("/", 1)[-1] in
                        {"config.txt", "engine-result.json", "shared.lock"} or "/.runtime/" in name):
                    raise AssertionError("Retired operational file accessed: " + name)
            return original(path, *args, **kwargs)
        return checked
    with ExitStack() as stack:
        stack.enter_context(mock.patch("builtins.open", side_effect=guarded_open(builtins.open)))
        stack.enter_context(mock.patch("io.open", side_effect=guarded_open(io.open)))
        stack.enter_context(mock.patch("os.open", side_effect=guarded_open(os.open)))
        for method in ("reader", "writer", "DictReader", "DictWriter"):
            stack.enter_context(mock.patch("csv." + method, side_effect=AssertionError("Runtime CSV IO used")))
        yield
