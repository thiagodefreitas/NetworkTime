# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Deprecation helpers for the stable API (:mod:`ntpstats.api`).

Policy (also in CONTRIBUTING.md): a stable name or parameter that changes
keeps working, with a :class:`NtpstatsDeprecationWarning`, for at least one
full minor release. It is removed no earlier than the release named in the
warning, and the removal is listed under *Removed* in the changelog.

The warning is a :class:`FutureWarning` subclass, so it is shown by default to
the people who run the code (scripts, notebooks), not only under test runners.
The test suite turns it into an error, so ntpstats never calls its own
deprecated names.
"""

from __future__ import annotations

import functools
import warnings
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class NtpstatsDeprecationWarning(FutureWarning):
    """A stable ntpstats name or parameter is deprecated and will be removed."""


def message(what: str, since: str, remove_in: str, use: Optional[str] = None) -> str:
    text = f"{what} is deprecated since ntpstats {since} and will be removed in {remove_in}"
    return text + (f"; use {use} instead" if use else "")


def warn(what: str, since: str, remove_in: str, use: Optional[str] = None, stacklevel: int = 3) -> None:
    warnings.warn(message(what, since, remove_in, use), NtpstatsDeprecationWarning, stacklevel=stacklevel)


def _note(doc: Optional[str], since: str, remove_in: str, use: Optional[str]) -> str:
    note = f"\n\n.. deprecated:: {since}\n   Removed in {remove_in}." + (f" Use {use}." if use else "")
    return (doc or "").rstrip() + note


def deprecated(since: str, remove_in: str, use: Optional[str] = None) -> Callable[[F], F]:
    """Mark a function (or a class, on instantiation) as deprecated."""

    def wrap(obj: F) -> F:
        what = f"{obj.__module__}.{obj.__qualname__}"
        if isinstance(obj, type):
            init = vars(obj).get("__init__") or obj.__init__  # type: ignore[misc]

            @functools.wraps(init)
            def __init__(self, *args, **kwargs):
                warn(what, since, remove_in, use)
                init(self, *args, **kwargs)

            obj.__init__ = __init__  # type: ignore[misc]
            obj.__doc__ = _note(obj.__doc__, since, remove_in, use)
            return obj

        @functools.wraps(obj)
        def inner(*args, **kwargs):
            warn(what, since, remove_in, use)
            return obj(*args, **kwargs)

        inner.__doc__ = _note(obj.__doc__, since, remove_in, use)
        return inner  # type: ignore[return-value]

    return wrap


def renamed_parameter(old: str, new: str, since: str, remove_in: str) -> Callable[[F], F]:
    """Accept ``old=`` as an alias of ``new=`` with a warning."""

    def wrap(fn: F) -> F:
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            if old in kwargs:
                if new in kwargs:
                    raise TypeError(f"{fn.__name__}() got both {old!r} (deprecated) and {new!r}")
                warn(f"parameter {old!r} of {fn.__name__}()", since, remove_in, f"{new!r}")
                kwargs[new] = kwargs.pop(old)
            return fn(*args, **kwargs)

        return inner  # type: ignore[return-value]

    return wrap


def moved(module: str, aliases: Dict[str, Tuple[str, str, str]]) -> Callable[[str], Any]:
    """A module ``__getattr__`` for names that moved.

    ``aliases`` maps an old name to ``("new.module:name", since, remove_in)``::

        __getattr__ = moved(__name__, {"old_name": ("ntpstats.x:new_name", "2.15", "2.17")})
    """

    def __getattr__(name: str) -> Any:
        if name not in aliases:
            raise AttributeError(f"module {module!r} has no attribute {name!r}")
        target, since, remove_in = aliases[name]
        mod, _, attr = target.partition(":")
        warn(f"{module}.{name}", since, remove_in, target.replace(":", "."))
        import importlib

        return getattr(importlib.import_module(mod), attr)

    return __getattr__
