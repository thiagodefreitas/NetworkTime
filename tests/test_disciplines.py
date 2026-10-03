"""Clock-discipline models: ntpd (reference implementation and RFC 5905 constants) and Levine's algorithms."""

import numpy as np
import pytest

from ntpstats import api
from ntpstats.disciplines import NTPD_CONSTANTS, _vote, lockclock, ntpd_discipline
from ntpstats.series import TimeSeries

T0 = 1_790_000_000.0


def clock(freq=20e-6, offset=0.0, noise=0.0, poll=64.0, hours=12, seed=1, delay=0.01):
    """Measurements of a free-running clock with a constant frequency error: reference - local = offset + freq t."""
    rng = np.random.default_rng(seed)
    t = T0 + np.arange(0, hours * 3600, poll)
    truth = offset + freq * (t - T0)
    meas = truth + rng.normal(0, noise, t.size) if noise else truth.copy()
    return TimeSeries(t, meas, name="clock", extra={"delay": np.full(t.size, delay)}), truth


def test_ntpd_type_ii_loop_removes_a_frequency_offset():
    # a frequency offset is a ramp of phase: a type II loop follows it with no steady-state error (thesis ch. 4)
    s, truth = clock(freq=20e-6)
    r = ntpd_discipline(s)
    late = r.t > T0 + 6 * 3600
    assert r.meta["frequency"] == pytest.approx(20e-6, abs=2e-9)
    assert np.max(np.abs(r.offset[late] - truth[late])) < 5e-6
    assert r.meta["state"] == "SYNC" and r.meta["steps"] == 0 and r.meta["poll"] == 6


def test_ntpd_steps_after_the_stepout_interval():
    s, truth = clock(freq=5e-6, offset=0.5, hours=4)
    r = ntpd_discipline(s)
    assert r.meta["steps"] >= 1
    late = r.t > T0 + 3 * 3600
    assert np.max(np.abs(r.offset[late] - truth[late])) < 1e-3
    # the first large offset in NSET is stepped at once; no correction before it is seen
    assert r.offset[0] == 0.0


def test_ntpd_drift_file_skips_the_frequency_measurement():
    s, truth = clock(freq=20e-6, hours=3)
    cold = ntpd_discipline(s)
    warm = ntpd_discipline(s, initial_frequency=20e-6)
    err = lambda r: np.sqrt(np.mean((r.offset - truth) ** 2))  # noqa: E731
    assert err(warm) < 0.2 * err(cold)


def test_rfc5905_appendix_constants_barely_correct_the_phase():
    # appendix A.5.6.1: offset / (PLL * min(2^poll, ALLAN)) per second, PLL = 65536: a time constant of
    # 65536 * 64 s (about 48 days) at poll 6, against 16 * 64 s with ntpd's constant
    assert NTPD_CONSTANTS["rfc5905"]["pll"] == 65536 and NTPD_CONSTANTS["ntpd"]["pll"] == 16
    s, truth = clock(freq=0.0, offset=0.01, hours=2)
    s.offset[:] = 0.0  # in sync at the start, then a 10 ms phase step of the reference after 10 minutes
    s.offset[s.t >= T0 + 600] = 0.01
    ntpd = ntpd_discipline(s, initial_frequency=0.0)
    rfc = ntpd_discipline(s, constants="rfc5905", initial_frequency=0.0)
    end = -1
    assert abs(0.01 - ntpd.offset[end]) < 1e-3          # ntpd: most of the step is absorbed in 100 minutes
    assert abs(0.01 - rfc.offset[end]) > 0.009         # RFC constants: less than 10 % of it


def test_ntpd_ignores_a_single_spike():
    s, truth = clock(freq=0.0, hours=3)
    s.offset[100] = 0.5  # one outlier above the step threshold
    r = ntpd_discipline(s, initial_frequency=0.0)
    assert r.meta["steps"] == 0
    assert np.max(np.abs(r.offset - truth)) < 1e-6


def test_vote_rejects_outliers_like_levine():
    assert _vote([1.0, 1.1, 0.9, 1.05, 9.0], sigma=0.1) == pytest.approx(np.mean([1.0, 1.1, 0.9, 1.05]))
    assert _vote([1.0, 1.02, 0.99, 1.01, 0.98], sigma=0.1) == pytest.approx(1.0)
    assert _vote([0.0, 5.0, 10.0, 15.0, 20.0], sigma=0.1) is None
    assert _vote([2.0], sigma=0.1) == 2.0


def test_lockclock_learns_the_frequency_and_tracks_through_noise():
    s, truth = clock(freq=20e-6, noise=200e-6, hours=24)
    r = lockclock(s)
    late = r.t > T0 + 12 * 3600
    assert r.meta["frequency"] == pytest.approx(20e-6, abs=0.3e-6)  # k = 1 averages only a few cycles
    assert r.meta["mode"] == "frequency"
    rms = np.sqrt(np.mean((r.offset[late] - truth[late]) ** 2))
    assert rms < 200e-6  # better than a single measurement


def test_levine_kalman_weights_clock_against_link():
    s, truth = clock(freq=20e-6, noise=500e-6, hours=24, seed=3)
    plain = lockclock(s)
    trust_link = lockclock(s, kalman=True, sigma_o=1.0)  # sigma_o >> sigma_t: the whole residual, as LOCKCLOCK
    assert trust_link.meta["gain"] == pytest.approx(1.0, abs=1e-6)
    assert np.allclose(trust_link.offset, plain.offset)
    online = lockclock(s, kalman=True)
    assert 0.0 <= online.meta["gain"] <= 1.0
    late = online.t > T0 + 12 * 3600
    assert online.meta["frequency"] == pytest.approx(20e-6, abs=0.3e-6)
    assert np.sqrt(np.mean((online.offset[late] - truth[late]) ** 2)) < 1e-3


@pytest.mark.parametrize("name", ["ntpd", "ntpd-rfc", "lockclock", "levine-kalman"])
def test_registered_in_the_bench(name):
    assert name in api.available_estimators()
    rows = api.run_bench(api.load_scenarios(["internet"]), estimators=[name, "raw"], seeds=[1], duration=6 * 3600)
    assert {r["estimator"] for r in rows} == {name, "raw"}
    assert all(np.isfinite(r["rms"]) for r in rows)


def test_ntpd_beats_raw_on_the_internet_preset():
    rows = api.run_bench(api.load_scenarios(["internet"]), estimators=["ntpd", "lockclock", "raw"], seeds=[1, 2])
    rms = {e: np.mean([r["rms"] for r in rows if r["estimator"] == e]) for e in ("ntpd", "lockclock", "raw")}
    assert rms["ntpd"] < rms["raw"] and rms["lockclock"] < rms["raw"]
