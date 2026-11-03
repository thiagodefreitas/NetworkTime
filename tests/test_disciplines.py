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



def test_ntpd_popcorn_gate_cannot_reject_a_spike_the_filter_selects():
    # ntp_proto.c computes the jitter around the newly selected sample, so a selected spike inflates it:
    # while the previous selection is still in the 8-stage register, jitter >= |jump| / sqrt(7) and the
    # gate (jump > 3 jitter) cannot open. An isolated low-delay spike is used, not suppressed.
    s, _ = clock(freq=0.0, noise=1e-5, hours=6, seed=4)
    i = int(np.searchsorted(s.t, T0 + 4 * 3600))
    s.offset[i] += 0.05
    s.extra["delay"][i] = 0.001
    r = ntpd_discipline(s, initial_frequency=0.0)
    assert r.meta["popcorns"] == 0
    assert np.max(np.abs(r.offset[i + 1:i + 30])) > 1e-3  # the spike was taken into the loop


def test_ntpd_popcorn_gate_fires_when_the_previous_selection_ages_out():
    # a low-delay spike is used and stays the best sample for eight polls; when it leaves the register the
    # next best sample is one poll newer than it and 20 ms away while the register agrees within 10 us:
    # that sample is dropped as popcorn once, then accepted
    s, _ = clock(freq=0.0, noise=1e-5, hours=6, seed=4)
    i = int(np.searchsorted(s.t, T0 + 4 * 3600))
    s.offset[i] += 0.02
    s.extra["delay"][i] = 0.001
    s.extra["delay"][i + 1] = 0.005
    on = ntpd_discipline(s, initial_frequency=0.0)
    off = ntpd_discipline(s, initial_frequency=0.0, popcorn=False)
    assert on.meta["popcorns"] == 1 and off.meta["popcorns"] == 0
    d = np.abs(on.offset - off.offset)
    assert d[: i + 9].max() == 0.0 and d[i + 9:].max() > 0.0  # identical until the gate fires


def test_ntpd_phase_step_is_accepted_at_once():
    s, _ = clock(freq=0.0, hours=3)
    s.offset[:] = 0.0
    s.offset[s.t >= T0 + 3600] = 0.01
    r = ntpd_discipline(s, initial_frequency=0.0)
    assert r.meta["popcorns"] == 0
    assert abs(0.01 - r.offset[-1]) < 2e-3


def test_ntpd_slew_is_bounded_at_500_ppm():
    # adj_host_clock(): |frequency + phase adjustment| <= NTP_MAXFREQ per second. During the startup clamp
    # the phase gain is offset / 32 per second, so a 100 ms offset would slew at about 3000 ppm unbounded.
    s, _ = clock(freq=0.0, offset=0.1, hours=1, poll=16.0)
    r = ntpd_discipline(s, initial_frequency=0.0)
    rate = np.diff(r.offset) / np.diff(r.t)
    assert np.max(np.abs(rate)) <= 500e-6 * (1 + 1e-9)
    assert np.max(np.abs(rate)) > 450e-6  # the bound is reached
    assert r.meta["steps"] == 0


# --------------------------------------------------------------- 3.9: poll adaptation and chrony
def test_ntpd_adapts_its_poll_between_minpoll_and_maxpoll():
    s, truth = clock(freq=10e-6, noise=20e-6, poll=64.0, hours=48, seed=3)
    r = ntpd_discipline(s, maxpoll=10)
    polls = r.extra["poll"]
    assert polls.min() >= 6 and polls.max() <= 10 and polls.max() > 6  # it climbs once the loop settles
    assert r.meta["minpoll"] == 6 and r.meta["maxpoll"] == 10 and r.meta["polls"][0] == (T0, 6)
    assert r.meta["measurements_used"] < len(s)  # only one measurement per current poll interval
    changes = [p for _, p in r.meta["polls"]]
    assert all(abs(a - b) == 1 for a, b in zip(changes, changes[1:]))  # one step at a time
    late = r.t > T0 + 24 * 3600
    assert np.sqrt(np.mean((r.offset[late] - truth[late]) ** 2)) < 1e-3
    with pytest.raises(ValueError):
        ntpd_discipline(s, poll=8, maxpoll=6)


def test_ntpd_fixed_poll_is_unchanged_by_the_adaptation_code():
    s, _ = clock(freq=10e-6, noise=20e-6, hours=12, seed=4)
    r = ntpd_discipline(s)
    assert "poll" not in r.extra and r.meta["measurements_used"] == len(s) and r.meta["poll"] == 6


def test_chrony_regression_and_runs_test():
    from ntpstats.disciplines import _best_regression, _runs

    assert _runs(np.array([1.0, 1.0, -1.0, 1.0])) == 3
    x = np.arange(-19.0, 1.0)
    y = 2.0 + 0.5 * x + np.where(np.arange(20) % 2, 0.01, -0.01)
    a, b, sb0, sb1, start, dof, var = _best_regression(x, y, np.ones(20), 20, 0, 1)
    assert (a, b, start) == (pytest.approx(2.0, abs=0.02), pytest.approx(0.5, abs=1e-3), 0)
    y2 = y.copy()
    y2[:10] += 1.0  # an old step: the residuals form two long runs, the old samples are dropped
    assert _best_regression(x, y2, np.ones(20), 20, 0, 1)[4] > 0
    assert _best_regression(x[:2], y[:2], np.ones(2), 2, 0, 1) is None


def test_chrony_removes_a_frequency_offset_and_reports_its_skew():
    from ntpstats.disciplines import chrony_discipline

    s, truth = clock(freq=20e-6, noise=50e-6, hours=24, seed=5)
    r = chrony_discipline(s)
    late = r.t > T0 + 12 * 3600
    assert r.meta["frequency"] == pytest.approx(20e-6, abs=0.2e-6)
    assert np.sqrt(np.mean((r.offset[late] - truth[late]) ** 2)) < 50e-6  # better than one measurement
    assert 0 < r.meta["skew"] < 1e-6 and r.meta["steps"] == 0


def test_chrony_makestep_and_delay_test():
    from ntpstats.disciplines import chrony_discipline

    s, truth = clock(freq=0.0, offset=2.0, hours=2, seed=6)
    r = chrony_discipline(s)
    assert r.meta["steps"] == 1 and abs(r.offset[-1] - truth[-1]) < 1e-3
    assert chrony_discipline(s, makestep=None).meta["steps"] == 0  # chrony's default: never step
    s, truth = clock(freq=5e-6, noise=10e-6, hours=12, seed=7, delay=0.010)
    s.extra["delay"][100::40] = 0.200  # queueing on one direction: delay +190 ms, offset +50 ms (< delay/2)
    s.offset[100::40] += 0.050
    on, off = chrony_discipline(s), chrony_discipline(s, maxdelaydevratio=0)
    assert on.meta["delay_rejected"] >= 5 and off.meta["delay_rejected"] == 0
    late = s.t > T0 + 6 * 3600

    def rms(r):
        return np.sqrt(np.mean((r.offset[late] - truth[late]) ** 2))
    assert rms(on) < rms(off)


def test_chrony_adapts_its_poll_to_the_polltarget():
    from ntpstats.disciplines import chrony_discipline

    s, truth = clock(freq=10e-6, noise=20e-6, poll=64.0, hours=48, seed=8)
    r = chrony_discipline(s, maxpoll=10)
    assert r.extra["poll"].max() == 10 and r.extra["poll"].min() >= 6
    assert r.meta["measurements_used"] < len(s) / 4
    late = r.t > T0 + 24 * 3600
    assert np.sqrt(np.mean((r.offset[late] - truth[late]) ** 2)) < 1e-3


def test_new_disciplines_are_bench_estimators():
    from ntpstats.estimators import available

    names = set(available())
    assert {"chrony", "ntpd-adaptive", "chrony-adaptive"} <= names
