"""ntpd-rs as a live source: its Prometheus text output (ntp-ctl -f prometheus status, metrics exporter)."""

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ntpstats.parsers import load
from ntpstats.sources import (
    SAMPLERS,
    LocalWatch,
    SourceError,
    parse_ntpdrs_metrics,
    parse_prometheus_text,
    sample_ntpdrs,
)

# The layout ntpd-rs 1.9 writes (ntpd/src/metrics/mod.rs): HELP, TYPE, UNIT, then labelled samples.
NTPDRS_19 = """\
# HELP ntp_system_root_delay_seconds Combined round-trip delay to the reference clock.
# TYPE ntp_system_root_delay_seconds gauge
# UNIT ntp_system_root_delay_seconds seconds
ntp_system_root_delay_seconds 0.0123
# HELP ntp_system_root_dispersion_seconds Combined uncertainty.
# TYPE ntp_system_root_dispersion_seconds gauge
# UNIT ntp_system_root_dispersion_seconds seconds
ntp_system_root_dispersion_seconds 0.0004
# HELP ntp_system_stratum Stratum of the local clock.
# TYPE ntp_system_stratum gauge
ntp_system_stratum 3
# HELP ntp_source_offset_seconds Offset between the upstream source and system time.
# TYPE ntp_source_offset_seconds gauge
# UNIT ntp_source_offset_seconds seconds
ntp_source_offset_seconds{name="ntpd-rs.pool.ntp.org:123",address="192.0.2.1:123",id="1"} 0.000200
ntp_source_offset_seconds{name="ntpd-rs.pool.ntp.org:123",address="192.0.2.2:123",id="2"} 0.000100
ntp_source_offset_seconds{name="time.example:123",address="198.51.100.9:123",id="3"} -0.004000
# HELP ntp_source_uncertainty_seconds Estimated error of the source clock.
# TYPE ntp_source_uncertainty_seconds gauge
# UNIT ntp_source_uncertainty_seconds seconds
ntp_source_uncertainty_seconds{name="ntpd-rs.pool.ntp.org:123",address="192.0.2.1:123",id="1"} 0.0001
ntp_source_uncertainty_seconds{name="ntpd-rs.pool.ntp.org:123",address="192.0.2.2:123",id="2"} 0.0001
ntp_source_uncertainty_seconds{name="time.example:123",address="198.51.100.9:123",id="3"} 0.0100
# HELP ntp_source_delay_seconds Current round-trip delay to the upstream source.
# TYPE ntp_source_delay_seconds gauge
# UNIT ntp_source_delay_seconds seconds
ntp_source_delay_seconds{name="ntpd-rs.pool.ntp.org:123",address="192.0.2.1:123",id="1"} 0.0021
ntp_source_delay_seconds{name="ntpd-rs.pool.ntp.org:123",address="192.0.2.2:123",id="2"} 0.0030
ntp_source_delay_seconds{name="time.example:123",address="198.51.100.9:123",id="3"} 0.0450
# EOF
"""

# ntpd-rs 2.0 pre-releases: per-source poll and cookies, but no offsets.
NTPDRS_20 = """\
ntp_system_stratum 2
ntp_source_poll_interval_seconds{name="a",address="192.0.2.1:123",id="1"} 16
ntp_source_unanswered_polls{name="a",address="192.0.2.1:123",id="1"} 0
"""


def test_prometheus_text_samples_and_label_escapes():
    rows = parse_prometheus_text('m{a="x\\"y",b="1"} 2.5 1700000000000\n# c\nbad line\nm2 3\n')
    assert rows == [("m", {"a": 'x"y', "b": "1"}, 2.5), ("m2", {}, 3.0)]


def test_ntpdrs_combination():
    d = parse_ntpdrs_metrics(NTPDRS_19)
    w = [1e8, 1e8, 1e4]
    expect = (w[0] * 2e-4 + w[1] * 1e-4 + w[2] * -4e-3) / sum(w)
    assert d["offset"] == pytest.approx(expect)
    assert d["sources"] == 3 and d["min_uncertainty"] == pytest.approx(1e-4) and d["delay"] == pytest.approx(0.0021)
    assert d["root_delay"] == pytest.approx(0.0123) and d["stratum"] == 3


def test_ntpdrs_20_without_offsets_is_explained():
    with pytest.raises(SourceError, match="2.0"):
        parse_ntpdrs_metrics(NTPDRS_20)
    with pytest.raises(SourceError, match="no ntpd-rs metrics"):
        parse_ntpdrs_metrics("# nothing\n")


def test_sample_from_metrics_exporter_url():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = NTPDRS_19.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/openmetrics-text")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        d = sample_ntpdrs([f"http://127.0.0.1:{srv.server_address[1]}/metrics"])
    finally:
        srv.shutdown()
    assert d["sources"] == 3 and "time" in d


def test_watch_ntpdrs_writes_a_loadable_log(tmp_path):
    assert "ntpd-rs" in SAMPLERS
    script = tmp_path / "fake_ntp_ctl.py"
    script.write_text(f"print({NTPDRS_19!r})\n")
    out = tmp_path / "watch.csv"
    LocalWatch("ntpd-rs", interval=0.01, out_path=str(out), count=3, cmd=[sys.executable, str(script)]).run()
    (s,) = load(str(out))
    assert len(s) == 3 and s.extra["sources"][0] == 3
