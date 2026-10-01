# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""ntpstats: NTP / network-time offset and stability analysis toolkit."""

__version__ = "2.16.0"
__author__ = "Thiago de Freitas"
__url__ = "https://github.com/thiagodefreitas/NetworkTime"
__license__ = "MIT"

from .parsers import load, load_one  # noqa: E402,F401
from .series import TimeSeries  # noqa: E402,F401
