# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Build u-blox UBX frames (NAV-CLOCK, NAV-TIMEUTC, TIM-TP) for tests and examples."""

import calendar
import struct
import time

GPS_EPOCH = 315964800
LEAP = 18


def frame(cls, mid, payload):
    body = bytes([cls, mid]) + struct.pack("<H", len(payload)) + payload
    a = b = 0
    for x in body:
        a = (a + x) & 0xFF
        b = (b + a) & 0xFF
    return b"\xb5\x62" + body + bytes([a, b])


def gps_week_tow(unix_utc):
    """GPS week and time of week (s) of a POSIX UTC time."""
    g = unix_utc - GPS_EPOCH + LEAP
    week = int(g // 604800)
    return week, g - week * 604800


def nav_clock(itow_ms, clkb_ns, clkd_ns_s, tacc_ns=5, facc_ps_s=60):
    return frame(0x01, 0x22, struct.pack("<IiiII", itow_ms, int(round(clkb_ns)), int(round(clkd_ns_s)), tacc_ns,
                                         facc_ps_s))


def nav_timeutc(itow_ms, unix_utc, tacc_ns=8, valid=0x07):
    whole = int(unix_utc // 1)
    tm = time.gmtime(whole)
    nano = int(round((unix_utc - whole) * 1e9))
    return frame(0x01, 0x21, struct.pack("<IIiHBBBBBB", itow_ms, tacc_ns, nano, tm.tm_year, tm.tm_mon, tm.tm_mday,
                                         tm.tm_hour, tm.tm_min, tm.tm_sec, valid))


def tim_tp(pulse_unix_utc, qerr_ps, utc_base=False):
    """TIM-TP for the pulse at ``pulse_unix_utc``: GPS time base by default (flags bit 0 = 0)."""
    if utc_base:
        g = pulse_unix_utc - GPS_EPOCH
        week = int(g // 604800)
        tow = g - week * 604800
    else:
        week, tow = gps_week_tow(pulse_unix_utc)
    tow_ms = int(tow * 1000)
    sub = int(round((tow * 1000 - tow_ms) * 2 ** 32))
    flags = (0x01 if utc_base else 0x00) | 0x02  # time base, UTC available
    return frame(0x0D, 0x01, struct.pack("<IIiHBB", tow_ms, sub, int(round(qerr_ps)), week, flags, 0))


def unix(y, mo, d, h=0, mi=0, s=0):
    return calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))
