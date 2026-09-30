# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Network Time Security (RFC 8915) measurement client.

Optional: needs ``pip install 'ntpstats[nts]'`` (pyOpenSSL for the TLS 1.3
keying-material exporter, which Python's ``ssl`` module does not expose, and
``cryptography`` for AEAD_AES_SIV_CMAC_256). The rest of ntpstats keeps
working without these.

Flow::

    session = NTSSession("time.cloudflare.com")   # NTS-KE over TLS 1.3, ALPN "ntske/1"
    r = session.query()                           # authenticated NTPv4 exchange
    r.offset, r.delay, session.cookies_left

* NTS-KE (RFC 8915 section 4): negotiates NTPv4 (protocol 0) and AEAD 15
  (AES-SIV-CMAC-256), receives cookies and an optional NTP server/port, and
  derives the C2S/S2C keys with the exporter label
  ``EXPORTER-network-time-security``.
* NTP (section 5): Unique Identifier, NTS Cookie, Cookie Placeholder and
  NTS Authenticator extension fields. The response is authenticated, its
  Unique Identifier checked, and the encrypted new cookies stored (cookies
  are single use). An NTS NAK (Kiss-o'-Death ``NTSN``) triggers a new key
  exchange on the next query.

Certificates are verified against the system trust store (or ``cafile``),
including the host name, unless ``verify=False`` (only for lab testing).
"""

from __future__ import annotations

import ipaddress
import os
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .sntp import (
    _PACKET,
    KissOfDeath,
    NTPError,
    NTPResult,
    _ntp_to_unix,
    _refid,
    _short,
)

ALPN = b"ntske/1"
EXPORTER_LABEL = b"EXPORTER-network-time-security"
PROTO_NTPV4 = 0
AEAD_AES_SIV_CMAC_256 = 15
KEY_LEN = 32

# NTS-KE record types
REC_END, REC_NEXT_PROTO, REC_ERROR, REC_WARNING, REC_AEAD, REC_COOKIE, REC_SERVER, REC_PORT = range(8)
#: NTP Server Deny (draft-ietf-ntp-nts-keyexchange-pool, IANA early allocation): ask a pool for another server
REC_SERVER_DENY = 13
# NTP extension field types
EF_UID, EF_COOKIE, EF_COOKIE_PLACEHOLDER, EF_AUTH = 0x0104, 0x0204, 0x0304, 0x0404


class NTSError(NTPError):
    pass


def _deps():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESSIV
        from OpenSSL import SSL
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise NTSError("NTS support needs: pip install 'ntpstats[nts]' (pyOpenSSL, cryptography)") from exc
    return SSL, AESSIV


# ----------------------------------------------------------------- NTS-KE
def _record(rtype: int, body: bytes = b"", critical: bool = True) -> bytes:
    return struct.pack("!HH", (0x8000 if critical else 0) | rtype, len(body)) + body


def _parse_records(data: bytes):
    off = 0
    while off + 4 <= len(data):
        t, ln = struct.unpack_from("!HH", data, off)
        body = data[off + 4: off + 4 + ln]
        if len(body) < ln:
            return
        yield t & 0x7FFF, bool(t & 0x8000), body
        off += 4 + ln
        if t & 0x7FFF == REC_END:
            return


def _hostname_matches(cert, host: str) -> bool:
    from cryptography import x509

    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip in san.get_values_for_type(x509.IPAddress)
    except ValueError:
        pass
    host = host.lower().rstrip(".")
    for name in san.get_values_for_type(x509.DNSName):
        name = name.lower().rstrip(".")
        if name == host:
            return True
        if name.startswith("*.") and "." in host and host.split(".", 1)[1] == name[2:]:
            return True
    return False


@dataclass
class NTSKeys:
    c2s: bytes
    s2c: bytes
    cookies: List[bytes]
    server: str
    port: int
    aead: int = AEAD_AES_SIV_CMAC_256
    warnings: List[int] = field(default_factory=list)


def _tcp_connect(host, port, timeout, family=0):
    errors = []
    for fam, st, proto, _, addr in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):
        try:
            sock = socket.socket(fam, st, proto)
        except OSError as exc:
            errors.append(f"{addr[0]}: {exc.strerror or exc}")
            continue
        sock.settimeout(timeout)
        try:
            sock.connect(addr)
            return sock
        except OSError as exc:
            sock.close()
            errors.append(f"{addr[0]}: {exc.strerror or exc}")
    raise NTSError(f"cannot connect to {host}:{port} ({'; '.join(errors) or 'none resolved'})")


def key_exchange(host: str, port: int = 4460, timeout: float = 5.0, verify: bool = True,
                 cafile: Optional[str] = None, family: int = 0, deny: Sequence[str] = ()) -> NTSKeys:
    """NTS-KE (RFC 8915). ``deny`` lists NTP server names already in use, sent
    as NTP Server Deny records so that an NTS pool returns a different one."""
    SSL, _ = _deps()
    ctx = SSL.Context(SSL.TLS_CLIENT_METHOD)
    ctx.set_min_proto_version(SSL.TLS1_3_VERSION)
    ctx.set_alpn_protos([ALPN])
    if verify:
        ctx.set_verify(SSL.VERIFY_PEER, lambda *a: a[-1])
        if cafile:
            ctx.load_verify_locations(cafile)
        else:
            ctx.set_default_verify_paths()
    sock = _tcp_connect(host, port, timeout, family)
    # pyOpenSSL needs a blocking socket; enforce the timeout in the kernel instead.
    sock.settimeout(None)
    tv = struct.pack("ll", int(timeout), int((timeout % 1) * 1e6))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, tv)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, tv)
    conn = SSL.Connection(ctx, sock)
    try:
        return _ke_session(conn, host, timeout, verify, SSL, deny)
    except SSL.Error as exc:
        raise NTSError(f"NTS-KE TLS error with {host}:{port}: {exc}") from exc


def _ke_session(conn, host, timeout, verify, SSL, deny: Sequence[str] = ()) -> "NTSKeys":
    try:
        conn.set_tlsext_host_name(host.encode())
        conn.set_connect_state()
        conn.do_handshake()
        if conn.get_alpn_proto_negotiated() != ALPN:
            raise NTSError("server did not negotiate ALPN ntske/1")
        if verify and not _hostname_matches(conn.get_peer_certificate().to_cryptography(), host):
            raise NTSError(f"certificate does not match host name {host}")
        conn.sendall(_record(REC_NEXT_PROTO, struct.pack("!H", PROTO_NTPV4))
                     + _record(REC_AEAD, struct.pack("!H", AEAD_AES_SIV_CMAC_256))
                     + b"".join(_record(REC_SERVER_DENY, d.encode("ascii"), critical=False) for d in deny)
                     + _record(REC_END))
        buf = b""
        deadline = time.monotonic() + timeout
        while True:
            try:
                chunk = conn.recv(4096)
            except SSL.ZeroReturnError:
                break
            if not chunk:
                break
            buf += chunk
            if any(t == REC_END for t, _, _ in _parse_records(buf)) or time.monotonic() > deadline:
                break
        c2s = conn.export_keying_material(EXPORTER_LABEL, KEY_LEN,
                                          struct.pack("!HHB", PROTO_NTPV4, AEAD_AES_SIV_CMAC_256, 0))
        s2c = conn.export_keying_material(EXPORTER_LABEL, KEY_LEN,
                                          struct.pack("!HHB", PROTO_NTPV4, AEAD_AES_SIV_CMAC_256, 1))
    finally:
        try:
            conn.shutdown()
        except Exception:
            pass
        conn.close()
    cookies, server, ntp_port, warnings, proto, aead = [], host, 123, [], None, None
    for t, _crit, body in _parse_records(buf):
        if t == REC_ERROR:
            raise NTSError(f"NTS-KE error code {struct.unpack('!H', body[:2])[0] if len(body) >= 2 else '?'}")
        if t == REC_WARNING:
            warnings.append(struct.unpack("!H", body[:2])[0])
        elif t == REC_NEXT_PROTO:
            proto = struct.unpack("!H", body[:2])[0] if body else None
        elif t == REC_AEAD:
            aead = struct.unpack("!H", body[:2])[0] if body else None
        elif t == REC_COOKIE:
            cookies.append(body)
        elif t == REC_SERVER:
            server = body.decode("ascii", errors="replace")
        elif t == REC_PORT:
            ntp_port = struct.unpack("!H", body[:2])[0]
    if proto != PROTO_NTPV4 or aead != AEAD_AES_SIV_CMAC_256:
        raise NTSError(f"server negotiated protocol {proto} / AEAD {aead}, need NTPv4 / AES-SIV-CMAC-256")
    if not cookies:
        raise NTSError("no cookies received")
    return NTSKeys(c2s, s2c, cookies, server, ntp_port, warnings=warnings)


# ------------------------------------------------------------------- NTP
def _ef4(t: int, body: bytes) -> bytes:
    """NTPv4 extension field (RFC 7822): length includes padding to 4 octets."""
    pad = (4 - (len(body) + 4) % 4) % 4
    return struct.pack("!HH", t, 4 + len(body) + pad) + body + b"\0" * pad


def _pad4(b: bytes) -> bytes:
    return b + b"\0" * ((4 - len(b) % 4) % 4)


def build_request(keys: NTSKeys, placeholders: int = 0):
    """Return (packet, transmit_nonce, unique_id)."""
    _, AESSIV = _deps()
    xmt = os.urandom(8)
    uid = os.urandom(32)
    hdr = bytearray(48)
    hdr[0] = (4 << 3) | 3
    hdr[40:48] = xmt
    cookie = keys.cookies.pop(0)
    aad = bytes(hdr) + _ef4(EF_UID, uid) + _ef4(EF_COOKIE, cookie)
    aad += b"".join(_ef4(EF_COOKIE_PLACEHOLDER, b"\0" * len(cookie)) for _ in range(placeholders))
    nonce = os.urandom(16)
    ct = AESSIV(keys.c2s).encrypt(b"", [aad, nonce])
    auth = struct.pack("!HH", len(nonce), len(ct)) + _pad4(nonce) + _pad4(ct)
    return aad + _ef4(EF_AUTH, auth), xmt, uid


def _extension_fields(data: bytes, start: int = 48):
    off = start
    while off + 4 <= len(data):
        t, ln = struct.unpack_from("!HH", data, off)
        if ln < 4 or off + ln > len(data):
            break
        yield off, t, data[off + 4: off + ln]
        off += ln


def verify_response(keys: NTSKeys, data: bytes, uid: bytes) -> List[bytes]:
    """Authenticate a server response; return the new cookies it carries."""
    _, AESSIV = _deps()
    from cryptography.exceptions import InvalidTag

    got_uid = None
    for off, t, body in _extension_fields(data):
        if t == EF_UID:
            got_uid = body[:32]
        elif t == EF_AUTH:
            nlen, clen = struct.unpack_from("!HH", body, 0)
            p = 4
            nonce = body[p: p + nlen]
            p += nlen + (-nlen % 4)
            ct = body[p: p + clen]
            try:
                plain = AESSIV(keys.s2c).decrypt(ct, [data[:off], nonce])
            except InvalidTag as exc:
                raise NTSError("NTS authentication of the response failed") from exc
            if got_uid != uid:
                raise NTSError("unique identifier mismatch")
            return [b for _, et, b in _extension_fields(plain, 0) if et == EF_COOKIE]
    raise NTSError("response is not NTS-authenticated")


class NTSSession:
    """Keeps keys and cookies; performs a new key exchange when needed."""

    def __init__(self, host: str, ke_port: int = 4460, timeout: float = 5.0, verify: bool = True,
                 cafile: Optional[str] = None, family: int = 0, deny: Sequence[str] = ()):
        self.host, self.ke_port, self.timeout, self.verify, self.cafile = host, ke_port, timeout, verify, cafile
        self.family = family
        self.deny = tuple(deny)
        self.keys: Optional[NTSKeys] = None

    @property
    def cookies_left(self) -> int:
        return len(self.keys.cookies) if self.keys else 0

    def _ensure_keys(self) -> NTSKeys:
        if self.keys is None or not self.keys.cookies:
            self.keys = key_exchange(self.host, self.ke_port, self.timeout, self.verify, self.cafile, self.family,
                                     deny=self.deny)
        return self.keys

    def query(self) -> NTPResult:
        keys = self._ensure_keys()
        want = max(0, 8 - len(keys.cookies) - 1)
        pkt, xmt, uid = build_request(keys, placeholders=min(want, 7))
        from .sntp import _udp_socket

        sock, addr = _udp_socket(keys.server, keys.port, self.family)
        with sock:
            sock.settimeout(self.timeout)
            t1_ns = time.time_ns()
            sock.send(pkt)
            src = addr
            while True:
                try:
                    data = sock.recv(4096)
                except socket.timeout as exc:
                    raise NTSError(f"timeout waiting for {keys.server}") from exc
                t4_ns = time.time_ns()
                if len(data) >= 48 and data[24:32] == xmt:
                    break
        (b0, stratum, poll, prec, rdelay, rdisp, refid, _ref, _org, rec, xm) = _PACKET.unpack(data[:48])
        if stratum == 0:
            code = refid.rstrip(b"\0").decode("ascii", errors="replace")
            # RFC 8915 s5.7: a (necessarily unauthenticated) NTS NAK is only
            # honoured if it echoes our Unique Identifier.
            uid_ok = any(t == EF_UID and body[:32] == uid for _, t, body in _extension_fields(data))
            if not uid_ok:
                raise NTSError(f"ignored Kiss-o'-Death {code} without matching unique identifier")
            if code == "NTSN":
                self.keys = None  # cookies rejected: redo NTS-KE next time
            raise KissOfDeath(code)
        new = verify_response(keys, data, uid)
        keys.cookies.extend(new)
        leap = b0 >> 6
        if leap == 3 or stratum >= 16:
            raise NTSError("server is not synchronised")
        t1, t4 = t1_ns / 1e9, t4_ns / 1e9
        t2, t3 = _ntp_to_unix(rec, t1), _ntp_to_unix(xm, t1)
        return NTPResult(
            server=self.host, address=str(src[0]), t1=t1, t2=t2, t3=t3, t4=t4,
            offset=((t2 - t1) + (t3 - t4)) / 2, delay=(t4_ns - t1_ns) / 1e9 - (t3 - t2),
            stratum=stratum, leap=leap, version=4, poll=poll, precision=2.0 ** prec,
            root_delay=_short(rdelay), root_dispersion=_short(rdisp), refid=_refid(stratum, refid),
            auth="nts",
        )


def pool_sessions(pool: str, n: int = 3, **kw) -> List[NTSSession]:
    """Up to ``n`` sessions with *different* NTP servers from an NTS pool.

    Each key exchange sends NTP Server Deny records (draft-ietf-ntp-nts-
    keyexchange-pool) for the servers already obtained. A pool that ignores
    them may return duplicates, which are dropped.
    """
    sessions: List[NTSSession] = []
    seen: List[str] = []
    for _ in range(2 * n):
        if len(sessions) >= n:
            break
        s = NTSSession(pool, deny=list(seen), **kw)
        keys = s._ensure_keys()
        if keys.server in seen:
            continue
        seen.append(keys.server)
        sessions.append(s)
    return sessions

