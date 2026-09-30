# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""NTS client against a local NTS-KE + NTS-NTP test server (RFC 8915)."""

import datetime
import os
import socket
import struct
import threading
import time

import pytest

SSL = pytest.importorskip("OpenSSL.SSL")
aead = pytest.importorskip("cryptography.hazmat.primitives.ciphers.aead")

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from ntpstats import nts  # noqa: E402

NTP_DELTA = 2208988800


def to_ntp(t):
    return ((int(t) + NTP_DELTA) << 32) | int((t % 1) * 2 ** 32)


def make_cert(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    import ipaddress

    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256()))
    cp, kp = tmp_path / "cert.pem", tmp_path / "key.pem"
    cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kp.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    return str(cp), str(kp)


class FakeNTS:
    def __init__(self, cert, key, offset=0.125, tamper=False):
        self.offset, self.tamper = offset, tamper
        self.cookies = {}
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.tcp = socket.socket()
        self.tcp.bind(("127.0.0.1", 0))
        self.tcp.listen(4)
        ctx = SSL.Context(SSL.TLS_SERVER_METHOD)
        ctx.set_min_proto_version(SSL.TLS1_3_VERSION)
        ctx.use_certificate_file(cert)
        ctx.use_privatekey_file(key)
        ctx.set_alpn_select_callback(lambda conn, protos: nts.ALPN if nts.ALPN in protos else SSL.NO_OVERLAPPING_PROTOCOLS)
        self.ctx = ctx
        self.ke_requests = 0
        threading.Thread(target=self._ke, daemon=True).start()
        threading.Thread(target=self._ntp, daemon=True).start()

    def _ke(self):
        while True:
            try:
                s, _ = self.tcp.accept()
            except OSError:
                return
            c = SSL.Connection(self.ctx, s)
            c.set_accept_state()
            c.do_handshake()
            buf = b""
            while not any(t == nts.REC_END for t, _, _ in nts._parse_records(buf)):
                buf += c.recv(4096)
            self.ke_requests += 1
            c2s = c.export_keying_material(nts.EXPORTER_LABEL, 32, struct.pack("!HHB", 0, 15, 0))
            s2c = c.export_keying_material(nts.EXPORTER_LABEL, 32, struct.pack("!HHB", 0, 15, 1))
            out = nts._record(nts.REC_NEXT_PROTO, struct.pack("!H", 0)) + nts._record(nts.REC_AEAD, struct.pack("!H", 15))
            for _ in range(8):
                ck = os.urandom(64)
                self.cookies[ck] = (c2s, s2c)
                out += nts._record(nts.REC_COOKIE, ck, critical=False)
            out += nts._record(nts.REC_SERVER, b"127.0.0.1", critical=False)
            out += nts._record(nts.REC_PORT, struct.pack("!H", self.udp.getsockname()[1]), critical=False)
            out += nts._record(nts.REC_END)
            c.sendall(out)
            c.shutdown()
            c.close()

    def _ntp(self):
        while True:
            try:
                data, addr = self.udp.recvfrom(4096)
            except OSError:
                return
            t2 = time.time() + self.offset
            uid = cookie = None
            for off, t, body in nts._extension_fields(data):
                if t == nts.EF_UID:
                    uid = body[:32]
                elif t == nts.EF_COOKIE:
                    cookie = body
                elif t == nts.EF_AUTH:
                    nlen, clen = struct.unpack_from("!HH", body, 0)
                    nonce = body[4:4 + nlen]
                    ct = body[4 + nlen + (-nlen % 4): 4 + nlen + (-nlen % 4) + clen]
                    c2s, s2c = self.cookies.pop(cookie)
                    aead.AESSIV(c2s).decrypt(ct, [data[:off], nonce])  # raises if client is wrong
            hdr = bytearray(48)
            hdr[0], hdr[1] = (4 << 3) | 4, 1
            hdr[12:16] = b"GPS\0"
            hdr[24:32] = data[40:48]
            struct.pack_into("!QQ", hdr, 32, to_ntp(t2), to_ntp(t2 + 1e-5))
            aad = bytes(hdr) + nts._ef4(nts.EF_UID, uid)
            newck = os.urandom(64)
            self.cookies[newck] = (c2s, s2c)
            nonce = os.urandom(16)
            key = os.urandom(32) if self.tamper else s2c
            ct = aead.AESSIV(key).encrypt(nts._ef4(nts.EF_COOKIE, newck), [aad, nonce])
            self.udp.sendto(aad + nts._ef4(nts.EF_AUTH, struct.pack("!HH", 16, len(ct)) + nonce + nts._pad4(ct)), addr)

    def close(self):
        self.udp.close()
        self.tcp.close()


@pytest.fixture
def pki(tmp_path):
    return make_cert(tmp_path)


def test_nts_session_offset_and_cookie_refresh(pki):
    srv = FakeNTS(*pki)
    try:
        sess = nts.NTSSession("localhost", ke_port=srv.tcp.getsockname()[1], cafile=pki[0])
        r = sess.query()
        assert r.auth == "nts" and r.offset == pytest.approx(0.125, abs=0.01) and r.refid == "GPS"
        assert sess.cookies_left == 8  # used one, got one back
        for _ in range(3):
            sess.query()
        assert srv.ke_requests == 1  # cookies reused, no new key exchange
    finally:
        srv.close()


def test_nts_rejects_forged_response(pki):
    srv = FakeNTS(*pki, tamper=True)
    try:
        sess = nts.NTSSession("localhost", ke_port=srv.tcp.getsockname()[1], cafile=pki[0])
        with pytest.raises(nts.NTSError, match="authentication"):
            sess.query()
    finally:
        srv.close()


def test_nts_verifies_certificate(pki, tmp_path):
    srv = FakeNTS(*pki)
    other_cert, _ = make_cert(tmp_path / "other" if (tmp_path / "other").mkdir() is None else tmp_path)
    try:
        with pytest.raises((nts.NTSError, SSL.Error)):
            nts.key_exchange("localhost", srv.tcp.getsockname()[1], cafile=other_cert)
    finally:
        srv.close()


def test_nts_tls_errors_are_ntserrors():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)

    def serve():
        c, _ = s.accept()
        c.sendall(b"HTTP/1.0 400 not tls\r\n\r\n")
        c.close()

    threading.Thread(target=serve, daemon=True).start()
    try:
        with pytest.raises(nts.NTSError):
            nts.key_exchange("127.0.0.1", s.getsockname()[1], verify=False, timeout=2)
    finally:
        s.close()
