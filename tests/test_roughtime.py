# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Roughtime client (draft-ietf-ntp-roughtime-19) against a local signing server."""

import base64
import json
import socket
import struct
import threading

import pytest

pytest.importorskip("cryptography")
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

from ntpstats import roughtime as rt  # noqa: E402
from ntpstats.cli import main  # noqa: E402

T0 = 1_790_000_000


def raw(pk):
    return pk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


class FakeServer:
    """Signs batches of requests the way draft-19 describes; knobs to misbehave."""

    def __init__(self, now=T0, radi=3, leaf="request", seconds=True):
        self.lt = Ed25519PrivateKey.generate()
        self.online = Ed25519PrivateKey.generate()
        self.now, self.radi, self.leaf, self.seconds = now, radi, leaf, seconds
        self.tamper = None
        self.dele_center = None
        self.public_key = raw(self.lt)

    def _dele(self):
        u = 1 if self.seconds else 10 ** 6
        c = self.now if self.dele_center is None else self.dele_center
        dele = rt.encode({rt.tag("PUBK"): raw(self.online), rt.tag("MINT"): struct.pack("<Q", (c - 86400) * u),
                          rt.tag("MAXT"): struct.pack("<Q", (c + 86400) * u)})
        return rt.encode({rt.tag("SIG"): self.lt.sign(rt.CTX_DELEGATION + dele), rt.tag("DELE"): dele})

    def respond(self, requests):
        leaves = []
        for req in requests:
            m = rt.decode(rt.unpacket(req))
            leaves.append(rt.H(b"\x00" + (req if self.leaf == "request" else m[rt.tag("NONC")])))
        levels = [leaves]
        while len(levels[-1]) > 1:
            cur = levels[-1] + ([levels[-1][-1]] if len(levels[-1]) % 2 else [])
            levels.append([rt.H(b"\x01" + cur[i] + cur[i + 1]) for i in range(0, len(cur), 2)])
        root = levels[-1][0]
        u = 1 if self.seconds else 10 ** 6
        srep = rt.encode({rt.tag("VER"): struct.pack("<I", rt.VERSION_DRAFT), rt.tag("RADI"): struct.pack("<I", self.radi * u),
                          rt.tag("MIDP"): struct.pack("<Q", self.now * u), rt.tag("VERS"): struct.pack("<2I", 1, rt.VERSION_DRAFT),
                          rt.tag("ROOT"): root})
        sig = self.online.sign(rt.CTX_RESPONSE + srep)
        cert = self._dele()
        out = []
        for idx, req in enumerate(requests):
            path, i = b"", idx
            for lvl in levels[:-1]:
                lv = lvl + ([lvl[-1]] if len(lvl) % 2 else [])
                path += lv[i ^ 1]
                i >>= 1
            msg = {rt.tag("SIG"): sig, rt.tag("NONC"): rt.decode(rt.unpacket(req))[rt.tag("NONC")],
                   rt.tag("TYPE"): struct.pack("<I", 1), rt.tag("PATH"): path, rt.tag("SREP"): srep,
                   rt.tag("CERT"): cert, rt.tag("INDX"): struct.pack("<I", idx)}
            if self.tamper:
                self.tamper(msg)
            out.append(rt.packet(rt.encode(msg)))
        return out


def test_message_roundtrip_and_request_layout():
    msg = {rt.tag("NONC"): b"\x01" * 32, rt.tag("VER"): struct.pack("<I", 1), rt.tag("PAD"): b""}
    assert rt.decode(rt.encode(msg)) == msg
    # tags are sorted as little-endian uint32: VER (0x00524556) < NONC (0x434e4f4e)
    assert rt.encode(msg)[4 + 8: 4 + 8 + 4] == b"PAD\x00"
    req = rt.build_request(b"\x02" * 32, b"\x03" * 32)
    assert req[:8] == b"ROUGHTIM" and len(rt.unpacket(req)) >= 1024
    m = rt.decode(rt.unpacket(req))
    assert m[rt.tag("TYPE")] == b"\x00" * 4 and m[rt.tag("SRV")] == rt.H(b"\xff" + b"\x03" * 32)
    assert struct.unpack("<4I", m[rt.tag("VER")]) == (1, rt.VERSION_DRAFT_08, rt.VERSION_DRAFT_11, rt.VERSION_DRAFT)
    assert set(m[rt.tag("ZZZZ")]) == {0}
    with pytest.raises(rt.RoughtimeError):
        rt.decode(struct.pack("<I", 2) + struct.pack("<I", 0) + rt.tag("NONC") + rt.tag("VER"))


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8])
def test_verify_single_and_batched(n):
    srv = FakeServer()
    reqs = [rt.build_request(bytes([k]) * 32, srv.public_key) for k in range(n)]
    for k, resp in enumerate(srv.respond(reqs)):
        r = rt.verify(reqs[k], resp, srv.public_key, "fake", T0 - 0.01, T0 + 0.03)
        assert r.midp == T0 and r.radi == 3 and r.leaf == "request" and r.version == rt.VERSION_DRAFT
        assert r.offset == pytest.approx(-0.01) and r.bound == pytest.approx(3.02)


def test_draft08_response_as_cloudflare_sends_it():
    """Draft 08 (Cloudflare): VER and NONC at the top level, no TYPE or VERS, nonce leaf, seconds."""
    srv = FakeServer(leaf="nonce")
    req = rt.build_request(b"\x09" * 32, srv.public_key)
    top = rt.decode(rt.unpacket(srv.respond([req])[0]))
    srep = rt.encode({rt.tag("RADI"): struct.pack("<I", 1), rt.tag("MIDP"): struct.pack("<Q", T0),
                      rt.tag("ROOT"): rt.H(b"\x00" + b"\x09" * 32)})
    msg = {rt.tag("SREP"): srep, rt.tag("SIG"): srv.online.sign(rt.CTX_RESPONSE + srep), rt.tag("CERT"): top[rt.tag("CERT")],
           rt.tag("VER"): struct.pack("<I", rt.VERSION_DRAFT_08), rt.tag("INDX"): struct.pack("<I", 0),
           rt.tag("NONC"): b"\x09" * 32, rt.tag("PATH"): b""}
    r = rt.verify(req, rt.packet(rt.encode(msg)), srv.public_key)
    assert r.version == rt.VERSION_DRAFT_08 and r.leaf == "nonce" and r.midp == T0 and r.radi == 1


def test_older_draft_semantics_accepted():
    srv = FakeServer(leaf="nonce", seconds=False)
    req = rt.build_request(b"\x05" * 32, srv.public_key)
    r = rt.verify(req, srv.respond([req])[0], srv.public_key)
    assert r.leaf == "nonce" and r.midp == pytest.approx(T0) and r.radi == pytest.approx(3)


@pytest.mark.parametrize("what", ["sig", "cert", "nonce", "type", "path", "indx", "midp", "wrongkey"])
def test_tampering_is_rejected(what):
    srv = FakeServer()
    reqs = [rt.build_request(bytes([k]) * 32, srv.public_key) for k in range(2)]
    key = srv.public_key
    if what == "sig":
        srv.tamper = lambda m: m.__setitem__(rt.tag("SIG"), bytes(64))
    elif what == "cert":
        other = FakeServer()
        srv.tamper = lambda m: m.__setitem__(rt.tag("CERT"), other._dele())
    elif what == "nonce":
        srv.tamper = lambda m: m.__setitem__(rt.tag("NONC"), b"\xee" * 32)
    elif what == "type":
        srv.tamper = lambda m: m.__setitem__(rt.tag("TYPE"), struct.pack("<I", 0))
    elif what == "path":
        srv.tamper = lambda m: m.__setitem__(rt.tag("PATH"), bytes(32))
    elif what == "indx":
        srv.tamper = lambda m: m.__setitem__(rt.tag("INDX"), struct.pack("<I", 2))  # extra INDX bit set
    elif what == "midp":
        srv.dele_center = T0 - 3 * 86400  # MIDP after the delegation's MAXT
    else:
        key = FakeServer().public_key
    with pytest.raises(rt.RoughtimeError):
        rt.verify(reqs[0], srv.respond(reqs)[0], key)


def test_merkle_root_rejects_extra_index_bits():
    leaf = rt.H(b"\x00x")
    assert rt.merkle_root(leaf, b"", 0) == leaf
    assert rt.merkle_root(leaf, b"", 1) is None
    node = rt.H(b"y")
    assert rt.merkle_root(leaf, node, 1) == rt.H(b"\x01" + node + leaf)


def _fake_query(servers):
    def q(server, nonce, timeout, tcp, **kw):
        srv = servers[server.name]
        req = rt.build_request(nonce, server.public_key)
        return rt.verify(req, srv.respond([req])[0], server.public_key, server.name, T0 - 0.05, T0 + 0.05)  # one local clock
    return q


def test_chained_measurement_consistent_and_report_verifies():
    fakes = {n: FakeServer(now=T0 + k) for k, n in enumerate("abc")}
    servers = [rt.Server(n, f.public_key, n, 2002) for n, f in fakes.items()]
    m = rt.measure(servers, rounds=2, query_fn=_fake_query(fakes))
    assert len(m.responses) == 6 and m.consistent and not m.errors
    lo, hi = m.local_bound()
    assert lo <= 0 <= hi + 2
    rep = m.malfeasance_report()
    assert "rand" not in rep["responses"][0] and "rand" in rep["responses"][1]
    chain = rt.verify_report(json.loads(json.dumps(rep)))
    assert [r.midp for r in chain] == [r.midp for r in m.responses]
    bad = json.loads(json.dumps(rep))
    bad["responses"][1]["rand"] = base64.b64encode(bytes(32)).decode()
    with pytest.raises(rt.RoughtimeError, match="chained"):
        rt.verify_report(bad)


def test_lying_server_is_a_causal_violation():
    fakes = {"good": FakeServer(now=T0), "liar": FakeServer(now=T0 - 3600)}
    servers = [rt.Server(n, f.public_key, n, 2002) for n, f in fakes.items()]
    m = rt.measure(servers, rounds=2, query_fn=_fake_query(fakes))
    assert not m.consistent and m.local_bound() is None
    names = {(m.responses[i].server, m.responses[j].server) for i, j in m.violations}
    assert ("good", "liar") in names
    rt.verify_report(m.malfeasance_report())  # the evidence is self-contained


def test_backoff_and_server_specs(tmp_path):
    assert rt.backoff(1) == 1 and rt.backoff(3) == 2.25 and rt.backoff(100) == 86400
    s = rt.Server.parse("roughtime.se")
    assert s.port == 2002 and len(s.public_key) == 32
    key = base64.b64encode(b"\x07" * 32).decode()
    s2 = rt.Server.parse(f"[::1]:2003={key}")
    assert (s2.host, s2.port) == ("::1", 2003)
    lst = tmp_path / "list.json"
    lst.write_text(json.dumps({"servers": [{"name": "x", "version": 1, "publicKeyType": "ed25519", "publicKey": key,
                                            "addresses": [{"protocol": "udp", "address": "x.test:2002"}]}]}))
    assert rt.load_servers(str(lst))[0].host == "x.test"
    assert len(rt.load_servers()) == len(rt.SERVERS)


def _udp_server(fake, sock):
    while True:
        try:
            data, addr = sock.recvfrom(4096)
        except OSError:
            return
        sock.sendto(fake.respond([data])[0], addr)


@pytest.fixture
def udp_fakes():
    out = []
    socks = []
    for k in range(2):
        f = FakeServer(now=T0 + k)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        threading.Thread(target=_udp_server, args=(f, s), daemon=True).start()
        out.append((f, s.getsockname()[1]))
        socks.append(s)
    yield out
    for s in socks:
        s.close()


def test_udp_query_and_cli(udp_fakes, tmp_path, capsys):
    (f, port), (g, port2) = udp_fakes
    r = rt.query(rt.Server("fake", f.public_key, "127.0.0.1", port), timeout=2)
    assert r.midp == T0 and r.rtt < 1
    specs = [f"127.0.0.1:{p}={base64.b64encode(x.public_key).decode()}" for x, p in udp_fakes]
    rep = tmp_path / "report.json"
    rc = main(["roughtime", *specs, "--timeout", "2", "--report", str(rep)])
    out = capsys.readouterr().out
    assert "consistent" in out and not rep.exists()  # report written only on malfeasance
    # now one server lies: the CLI exits 3 and writes the report
    g.now = T0 - 7200
    rc = main(["roughtime", *specs, "--timeout", "2", "--report", str(rep), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 3 and not doc["consistent"] and doc["causal_violations"]
    assert len(json.loads(rep.read_text())["responses"]) == 4
    assert main(["roughtime", "--verify-report", str(rep)]) == 3
