# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Deprecation helpers: warnings are visible, old spellings keep working."""

import types
import warnings

import pytest

from ntpstats.deprecation import NtpstatsDeprecationWarning, deprecated, moved, renamed_parameter


def test_warning_is_visible_by_default():
    assert issubclass(NtpstatsDeprecationWarning, FutureWarning)  # shown outside test runners too


def test_deprecated_function_still_works_and_says_what_to_use():
    @deprecated("2.15", "2.17", use="new_fn()")
    def old_fn(x, y=1):
        """Add."""
        return x + y

    with pytest.warns(NtpstatsDeprecationWarning, match=r"since ntpstats 2\.15.*removed in 2\.17.*use new_fn\(\)"):
        assert old_fn(1, y=2) == 3
    assert "deprecated:: 2.15" in old_fn.__doc__ and old_fn.__name__ == "old_fn"


def test_deprecated_class_warns_on_instantiation():
    @deprecated("2.15", "3.0")
    class Old:
        def __init__(self, v):
            self.v = v

    with pytest.warns(NtpstatsDeprecationWarning):
        assert Old(4).v == 4


def test_warning_points_at_the_caller():
    @deprecated("2.15", "3.0")
    def f():
        return 1

    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        f()
    assert rec[0].filename == __file__


def test_renamed_parameter():
    @renamed_parameter("tau", "tau0", "2.15", "2.17")
    def f(x, tau0=1.0):
        return x * tau0

    assert f(2, tau0=3) == 6
    with pytest.warns(NtpstatsDeprecationWarning, match="'tau'"):
        assert f(2, tau=3) == 6
    with pytest.raises(TypeError, match="both"):
        f(2, tau=3, tau0=3)


def test_moved_names():
    mod = types.ModuleType("ntpstats_fake")
    mod.__getattr__ = moved("ntpstats_fake", {"old_load": ("ntpstats.parsers:load", "2.15", "2.17")})
    from ntpstats.parsers import load

    with pytest.warns(NtpstatsDeprecationWarning, match="ntpstats.parsers.load"):
        assert mod.old_load is load
    with pytest.raises(AttributeError):
        mod.nothing  # noqa: B018


def test_suite_turns_deprecations_into_errors():
    @deprecated("2.15", "3.0")
    def f():
        return 1

    with pytest.raises(NtpstatsDeprecationWarning):
        f()
