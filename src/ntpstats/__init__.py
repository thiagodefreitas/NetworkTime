# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas <thiagodefreitas@gmail.com>
"""ntpstats: NTP / network-time offset and stability analysis toolkit."""

__version__ = "2.3.0"
__author__ = "Thiago de Freitas"
__email__ = "thiagodefreitas@gmail.com"
__license__ = "MIT"

from .series import TimeSeries  # noqa: E402,F401
from .parsers import load, load_one  # noqa: E402,F401
