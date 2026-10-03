"""Poll-interval advice from the noise model and the holdover prediction."""

import json

import numpy as np
import pytest

from ntpstats import api
from ntpstats.cli import main
from ntpstats.noisefit import simulate
from ntpstats.series import TimeSeries

T0 = 1_790_000_000.0


def log(link=1e-3, h_fm=None, poll=64.0, n=4096, seed=1, freq=20e-6):
    """Offsets of a clock measured through a link: white phase noise ``link`` (s rms) plus clock noise ``h_fm``."""
    rng = np.random.default_rng(seed)
    t = T0 + poll * np.arange(n)
    x = freq * (t - T0) + rng.normal(0, link, n)
    if h_fm:
        x = x + simulate(h_fm, n, poll, seed=seed + 1)
    return TimeSeries(t, x, name="log")


def test_link_dominated_error_hardly_grows_with_the_interval():
    a = api.poll_advice(log(link=1e-3), target=5e-3, uncertainty=0)
    assert a.intervals[0] == pytest.approx(64.0) and a.intervals[1] == pytest.approx(128.0)
    assert np.all(np.diff(a.error) >= 0)  # never smaller for a longer interval
    assert a.error[-1] < 2 * a.error[0]
    assert a.recommended == a.intervals[-1]
    assert a.samples[-1] >= 32


def test_clock_dominated_error_grows_and_limits_the_interval():
    a = api.poll_advice(log(link=1e-6, h_fm={0: 1e-17, -2: 1e-24}), uncertainty=0)
    assert a.error[-1] > 5 * a.error[0]
    target = float(np.sqrt(a.error[0] * a.error[-1]))
    b = api.poll_advice(log(link=1e-6, h_fm={0: 1e-17, -2: 1e-24}), target=target, uncertainty=0)
    assert b.intervals[0] <= b.recommended < b.intervals[-1]
    assert api.poll_advice(log(link=1e-6), target=1e-12, uncertainty=0).recommended is None


def test_too_short_a_log_is_refused():
    with pytest.raises(ValueError, match="measurements"):
        api.poll_advice(log(n=20))


def test_cli(tmp_path, capsys):
    p = tmp_path / "log.csv"
    s = log(link=1e-3, n=1024)
    p.write_text("unix_time,offset\n" + "".join(f"{a:.3f},{b:.9f}\n" for a, b in zip(s.t, s.offset)))
    assert main(["poll", str(p), "--target", "10ms", "--uncertainty", "0"]) == 0
    out = capsys.readouterr().out
    assert "64 s (2^6, 1.07 min)" in out and "[PASS]" in out
    assert main(["poll", str(p), "--target", "1ns", "--uncertainty", "0", "--json"]) == 3
    d = json.loads(capsys.readouterr().out)[0]
    assert d["recommended"] is None and len(d["intervals"]) == len(d["error"])
