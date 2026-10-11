# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Step responses of the RFC 5905 appendix clock discipline, as printed and with the constants of the
RFC's own Figure 27, against the model of ntpd 4.2.8 (evidence for erratum 1 in README.md).

A noise-free reference is measured every 64 s (poll 6). After 10 minutes it steps by 10 ms (phase step)
or starts to drift at 10 ppm (frequency step). Run: python research/rfc5905-errata/reproduce.py
"""

import numpy as np

from ntpstats import disciplines as D
from ntpstats.series import TimeSeries

T0 = 1_790_000_000.0


def response(constants, kind):
    t = T0 + np.arange(0, 12 * 3600, 64.0)
    on = t >= T0 + 600
    truth = np.where(on, 0.01, 0.0) if kind == "phase" else np.where(on, 10e-6 * (t - T0 - 600), 0.0)
    s = TimeSeries(t, truth.copy(), extra={"delay": np.full(t.size, 0.01)})
    r = D.ntpd_discipline(s, constants=constants, initial_frequency=0.0)
    tt, e = t[on], np.abs(r.offset - truth)[on]
    settle = next((tt[k] - tt[0] for k in range(e.size) if np.all(e[k:] < 1e-3)), None)
    at = lambda h: e[np.searchsorted(tt, tt[0] + h * 3600)]  # noqa: E731
    return settle, at(1), at(10)


def main():
    printed = dict(D.NTPD_CONSTANTS["rfc5905"])
    cases = [("RFC 5905 appendix as printed (PLL 65536, AVG 4)", "rfc5905", {}),
             ("RFC 5905 appendix, PLL 16 and AVG 8 (Figure 27)", "rfc5905", {"pll": 16.0, "avg": 8.0}),
             ("ntpd 4.2.8 (ntp_loopfilter.c)", "ntpd", None)]
    print(f"{'loop':50} {'step':10} {'below 1 ms after':>17} {'error at 1 h':>13} {'error at 10 h':>14}")
    try:
        for label, const, patch in cases:
            if patch is not None:
                D.NTPD_CONSTANTS["rfc5905"] = dict(printed, **patch)
            for kind in ("phase", "frequency"):
                settle, e1, e10 = response(const, kind)
                st = f"{settle / 60:.0f} min" if settle is not None else "not in 12 h"
                print(f"{label:50} {kind:10} {st:>17} {e1 * 1e3:>10.2f} ms {e10 * 1e3:>11.2f} ms")
    finally:
        D.NTPD_CONSTANTS["rfc5905"] = printed


if __name__ == "__main__":
    main()
