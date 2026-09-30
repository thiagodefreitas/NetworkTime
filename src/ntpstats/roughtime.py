# SPDX-License-Identifier: MIT
# Copyright (c) 2012-2026 Thiago de Freitas (https://github.com/thiagodefreitas)
"""Roughtime client (draft-ietf-ntp-roughtime-19).

Roughtime gives a *signed*, coarse (about 1 s) time from several servers and
makes a lying server provable: every request nonce is derived from the
previous response, so a chain of responses shows the order in which they
were received. If two responses cannot both be right, the chain is a
**malfeasance report** anyone can verify.

For ntpstats this is an independent, authenticated sanity bound: an NTP or
PTP clock that disagrees with Roughtime by more than the Roughtime radius
is wrong, whatever its own statistics say.

Signature checks need ``cryptography`` (``pip install 'ntpstats[nts]'``).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

MAGIC = b"ROUGHTIM"
VERSION_1 = 1
VERSION_DRAFT = 0x8000000C  # draft-ietf-ntp-roughtime-12 and later (testing number, draft-19)
VERSION_DRAFT_11 = 0x8000000B
VERSION_DRAFT_08 = 0x80000008  # still the only IETF version of some deployed servers (Cloudflare)
DEFAULT_VERSIONS = (VERSION_1, VERSION_DRAFT_08, VERSION_DRAFT_11, VERSION_DRAFT)
MIN_REQUEST = 1024
CTX_DELEGATION = b"RoughTime v1 delegation signature\x00"
CTX_DELEGATION_OLD = b"RoughTime v1 delegation signature--\x00"  # Google Roughtime and early drafts
CTX_RESPONSE = b"RoughTime v1 response signature\x00"

# Public servers, from the Roughtime ecosystem list
# (https://github.com/cloudflare/roughtime/blob/master/ecosystem.json, retrieved 2026-09).
# Keys are long-term Ed25519 public keys; check them against the operators' own publications
# before relying on them.
SERVERS = [
    {"name": "Cloudflare-Roughtime-2", "publicKey": "0GD7c3yP8xEc4Zl2zeuN2SlLvDVVocjsPSL8/Rl/7zg=",
     "address": "roughtime.cloudflare.com:2003"},
    {"name": "int08h-Roughtime", "publicKey": "AW5uAoTSTDfG5NfY1bTh08GUnOqlRb+HVhbJ3ODJvsE=",
     "address": "roughtime.int08h.com:2002"},
    {"name": "roughtime.se", "publicKey": "S3AzfZJ5CjSdkJ21ZJGbxqdYP/SoE8fXKY0+aicsehI=",
     "address": "roughtime.se:2002"},
    {"name": "time.txryan.com", "publicKey": "iBVjxg/1j7y1+kQUTBYdTabxCppesU/07D4PMDJk2WA=",
     "address": "time.txryan.com:2002"},
]


class RoughtimeError(Exception):
    """Malformed, unverifiable or missing response."""


def H(data: bytes, size: int = 32) -> bytes:
    """SHA-512 truncated to ``size`` bytes (32 in the IETF drafts)."""
    return hashlib.sha512(data).digest()[:size]


def tag(name: str) -> bytes:
    return name.encode("ascii").ljust(4, b"\x00")


def _tag_key(t: bytes) -> int:
    return int.from_bytes(t, "little")


# ------------------------------------------------------------------ messages
def encode(msg: Dict[bytes, bytes]) -> bytes:
    """Roughtime message: N, N-1 offsets, N tags (sorted as uint32 LE), values."""
    tags = sorted(msg, key=_tag_key)
    offsets, pos = [], 0
    for i, t in enumerate(tags):
        v = msg[t]
        if len(v) % 4:
            raise ValueError(f"value of {t!r} is not a multiple of 4 bytes")
        if i:
            offsets.append(pos)
        pos += len(v)
    return (struct.pack(f"<{1 + len(offsets)}I", len(tags), *offsets) + b"".join(tags)
            + b"".join(msg[t] for t in tags))


def decode(buf: bytes) -> Dict[bytes, bytes]:
    if len(buf) < 4:
        raise RoughtimeError("message too short")
    (n,) = struct.unpack_from("<I", buf)
    if n == 0 or n > 1024:
        raise RoughtimeError(f"bad tag count {n}")
    hdr = 4 + 4 * (n - 1) + 4 * n
    if len(buf) < hdr:
        raise RoughtimeError("truncated header")
    offsets = [0, *struct.unpack_from(f"<{n - 1}I", buf, 4)]
    tags = [buf[4 * n + 4 * i: 4 * n + 4 * i + 4] for i in range(n)]
    vlen = len(buf) - hdr
    ends = offsets[1:] + [vlen]
    out = {}
    for i, t in enumerate(tags):
        if i and _tag_key(t) <= _tag_key(tags[i - 1]):
            raise RoughtimeError("tags not strictly ascending")
        a, b = offsets[i], ends[i]
        if a % 4 or a > b or b > vlen:
            raise RoughtimeError("bad value offset")
        out[t] = buf[hdr + a: hdr + b]
    return out


def packet(message: bytes) -> bytes:
    return MAGIC + struct.pack("<I", len(message)) + message


def unpacket(data: bytes) -> bytes:
    if len(data) < 12 or data[:8] != MAGIC:
        raise RoughtimeError("not a Roughtime packet")
    (n,) = struct.unpack_from("<I", data, 8)
    if 12 + n > len(data):
        raise RoughtimeError("truncated packet")
    return data[12: 12 + n]


def _u32(v: bytes) -> int:
    if len(v) != 4:
        raise RoughtimeError("bad uint32")
    return struct.unpack("<I", v)[0]


def _u64(v: bytes) -> int:
    if len(v) != 8:
        raise RoughtimeError("bad uint64")
    return struct.unpack("<Q", v)[0]


def build_request(nonce: bytes, public_key: Optional[bytes] = None,
                  versions: Sequence[int] = DEFAULT_VERSIONS, min_size: int = MIN_REQUEST) -> bytes:
    """Request packet: VER, NONC, TYPE=0, SRV (when the key is known), ZZZZ padding."""
    if len(nonce) != 32:
        raise ValueError("nonce must be 32 bytes")
    msg = {tag("VER"): b"".join(struct.pack("<I", v) for v in sorted(set(versions))),
           tag("NONC"): nonce, tag("TYPE"): struct.pack("<I", 0)}
    if public_key is not None:
        msg[tag("SRV")] = H(b"\xff" + public_key)
    size = len(encode(msg))
    if size + 8 < min_size:
        msg[tag("ZZZZ")] = bytes(-(-(min_size - size - 8) // 4) * 4)
    return packet(encode(msg))


# ------------------------------------------------------------------ verification
def _verify_sig(public_key: bytes, sig: bytes, data: bytes) -> bool:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover
        raise RoughtimeError("Roughtime needs: pip install 'ntpstats[nts]' (cryptography)") from exc
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(sig, data)
        return True
    except (InvalidSignature, ValueError):
        return False


def merkle_root(leaf: bytes, path: bytes, index: int, size: int = 32) -> Optional[bytes]:
    """Root from a leaf hash, PATH and INDX (draft-19 section 5.3.1); None if INDX has extra bits."""
    if len(path) % size:
        return None
    h = leaf
    for k in range(len(path) // size):
        node = path[k * size: (k + 1) * size]
        h = H(b"\x01" + h + node, size) if not index & 1 else H(b"\x01" + node + h, size)
        index >>= 1
    return None if index else h


def _timestamp(v: int, micro: bool) -> float:
    if not micro:
        return float(v)
    if v >= 10 ** 16:  # early drafts: MJD in the top 24 bits, microseconds of the day below
        return (v >> 40) * 86400.0 - 40587 * 86400.0 + (v & (2 ** 40 - 1)) / 1e6
    return v / 1e6


@dataclass
class Response:
    """A verified Roughtime response and the local times around it."""

    server: str
    midp: float  # server's time at processing (Unix seconds)
    radi: float  # radius (s): the true time was within midp +- radi
    version: int
    t_send: float  # local clock, Unix seconds
    t_recv: float
    request: bytes = field(repr=False)
    response: bytes = field(repr=False)
    public_key: bytes = field(repr=False)
    rand: Optional[bytes] = field(default=None, repr=False)
    mint: float = 0.0
    maxt: float = 0.0
    leaf: str = "request"  # what the Merkle leaf covered: "request" (draft-19) or "nonce" (older drafts)

    @property
    def rtt(self) -> float:
        return self.t_recv - self.t_send

    @property
    def offset(self) -> float:
        """Server - local, at the local midpoint (reference - local, like the rest of ntpstats)."""
        return self.midp - (self.t_send + self.t_recv) / 2

    @property
    def bound(self) -> float:
        """|true offset - offset| <= radius + rtt/2."""
        return self.radi + self.rtt / 2

    def as_dict(self) -> Dict[str, object]:
        return {"server": self.server, "midp": self.midp, "radi": self.radi, "version": hex(self.version),
                "t_send": self.t_send, "t_recv": self.t_recv, "rtt": self.rtt, "offset": self.offset,
                "bound": self.bound, "mint": self.mint, "maxt": self.maxt, "merkle_leaf": self.leaf}


def verify(request: bytes, response: bytes, public_key: bytes, server: str = "",
           t_send: float = 0.0, t_recv: float = 0.0) -> Response:
    """Check a response against its request and the server's long-term key (draft-19 section 5.4).

    Raises :class:`RoughtimeError` on any failure. Older drafts that sign the
    nonce instead of the request, and microsecond timestamps, are accepted.
    """
    req = decode(unpacket(request))
    nonce = req.get(tag("NONC"), b"")
    top = decode(unpacket(response))
    try:
        sig, srep_raw, cert_raw = top[tag("SIG")], top[tag("SREP")], top[tag("CERT")]
        path, index = top.get(tag("PATH"), b""), _u32(top[tag("INDX")])
        cert = decode(cert_raw)
        cert_sig, dele_raw = cert[tag("SIG")], cert[tag("DELE")]
        dele = decode(dele_raw)
        pubk = dele[tag("PUBK")]
        srep = decode(srep_raw)
        root = srep[tag("ROOT")]
        radi_raw, midp_raw = _u32(srep[tag("RADI")]), _u64(srep[tag("MIDP")])
        mint_raw, maxt_raw = _u64(dele[tag("MINT")]), _u64(dele[tag("MAXT")])
    except KeyError as exc:
        raise RoughtimeError(f"response lacks tag {exc.args[0]!r}") from None
    if tag("TYPE") in top and _u32(top[tag("TYPE")]) != 1:
        raise RoughtimeError("TYPE is not 1 (response)")
    got = top.get(tag("NONC"), srep.get(tag("NONC")))
    if got != nonce:
        raise RoughtimeError("nonce does not match the request")
    ver_raw = srep.get(tag("VER"), top.get(tag("VER"), b""))
    version = _u32(ver_raw[:4]) if len(ver_raw) >= 4 else 0
    offered = req.get(tag("VER"), b"")
    if version and offered and struct.pack("<I", version) not in [offered[i:i + 4] for i in range(0, len(offered), 4)]:
        raise RoughtimeError(f"server chose version {version:#x}, which was not offered")
    if not any(_verify_sig(public_key, cert_sig, ctx + dele_raw) for ctx in (CTX_DELEGATION, CTX_DELEGATION_OLD)):
        raise RoughtimeError("delegation (CERT) signature does not verify with the long-term key")
    if not _verify_sig(pubk, sig, CTX_RESPONSE + srep_raw):
        raise RoughtimeError("response (SREP) signature does not verify with the delegated key")
    micro = midp_raw >= 10 ** 11  # draft-19: seconds; older drafts: microseconds (or MJD)
    midp, mint, maxt = (_timestamp(v, micro) for v in (midp_raw, mint_raw, maxt_raw))
    if not mint <= midp <= maxt:
        raise RoughtimeError("MIDP outside the delegation's validity (MINT..MAXT)")
    size = len(root)
    leaf = None
    for kind, data in (("request", request), ("nonce", nonce)):
        if merkle_root(H(b"\x00" + data, size), path, index, size) == root:
            leaf = kind
            break
    if leaf is None:
        raise RoughtimeError("Merkle proof (PATH/INDX) does not lead to ROOT")
    radi = radi_raw / 1e6 if micro else float(radi_raw)
    if radi <= 0:
        raise RoughtimeError("RADI is zero")
    return Response(server=server, midp=midp, radi=radi, version=version, t_send=t_send, t_recv=t_recv,
                    request=request, response=response, public_key=public_key, mint=mint, maxt=maxt, leaf=leaf)


# ------------------------------------------------------------------ servers and transport
@dataclass
class Server:
    name: str
    public_key: bytes
    host: str
    port: int
    protocol: str = "udp"

    @classmethod
    def parse(cls, spec: str, known: Optional[List["Server"]] = None) -> "Server":
        """``NAME`` (from the list), or ``host:port=BASE64KEY``."""
        for s in known if known is not None else load_servers():
            if spec in (s.name, s.host, f"{s.host}:{s.port}"):
                return s
        if "=" not in spec:
            raise ValueError(f"unknown Roughtime server {spec!r}; use host:port=BASE64KEY")
        addr, key = spec.split("=", 1)
        host, port = _split_addr(addr)
        return cls(addr, _key(key), host, port)


def _split_addr(addr: str) -> Tuple[str, int]:
    host, _, port = addr.rpartition(":")
    if not host:
        return addr, 2002
    return host.strip("[]"), int(port)


def _key(b64: str) -> bytes:
    k = base64.b64decode(b64)
    if len(k) != 32:
        raise ValueError("Ed25519 public keys are 32 bytes")
    return k


def load_servers(source: Optional[str] = None) -> List[Server]:
    """Servers from a draft-19 server list (JSON, section 8.3), or the bundled list."""
    entries: List[Dict[str, Any]]
    if source is None:
        entries = [{"name": e["name"], "publicKey": e["publicKey"], "publicKeyType": "ed25519",
                    "addresses": [{"protocol": "udp", "address": e["address"]}]} for e in SERVERS]
    else:
        with open(source, encoding="utf-8") as fh:
            entries = json.load(fh)["servers"]
    out = []
    for e in entries:
        if e.get("publicKeyType", "ed25519") != "ed25519":
            continue
        addrs = e.get("addresses") or []
        a = next((x for x in addrs if x.get("protocol") == "udp"), addrs[0] if addrs else None)
        if a is None:
            continue
        host, port = _split_addr(a["address"])
        out.append(Server(e["name"], _key(e["publicKey"]), host, port, a.get("protocol", "udp")))
    return out


def backoff(n: int, base: float = 1.0) -> float:
    """Minimum wait before retry ``n`` (1-based): min(base * 1.5**(n-1), 86400) s (draft-19 section 5)."""
    return min(base * 1.5 ** (n - 1), 86400.0)


def _exchange(server: Server, request: bytes, timeout: float, tcp: bool, family: int) -> Tuple[bytes, float, float]:
    infos = socket.getaddrinfo(server.host, server.port, family, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM)
    af, st, proto, _, addr = infos[0]
    with socket.socket(af, st, proto) as sock:
        sock.settimeout(timeout)
        if tcp:
            sock.connect(addr)
            t1 = time.time()
            sock.sendall(request)
            buf = b""
            while len(buf) < 12 or len(buf) < 12 + struct.unpack_from("<I", buf, 8)[0]:
                chunk = sock.recv(65536)
                if not chunk:
                    raise RoughtimeError("connection closed")
                buf += chunk
            return buf, t1, time.time()
        t1 = time.time()
        sock.sendto(request, addr)
        while True:
            data, _ = sock.recvfrom(65536)
            t4 = time.time()
            if data[:8] == MAGIC:
                return data, t1, t4


def query(server: Server, nonce: Optional[bytes] = None, timeout: float = 3.0, tcp: bool = False,
          retries: int = 0, versions: Sequence[int] = DEFAULT_VERSIONS, family: int = 0,
          sleep: Callable[[float], None] = time.sleep) -> Response:
    """One verified exchange. UDP by default; ``tcp=True`` for paths that drop large datagrams."""
    nonce = nonce if nonce is not None else os.urandom(32)
    request = build_request(nonce, server.public_key, versions)
    last: Exception = RoughtimeError("no attempt")
    for attempt in range(retries + 1):
        if attempt:
            sleep(backoff(attempt))
        try:
            data, t1, t4 = _exchange(server, request, timeout, tcp, family)
            return verify(request, data, server.public_key, server.name, t1, t4)
        except (OSError, RoughtimeError) as exc:
            last = exc
    raise last if isinstance(last, RoughtimeError) else RoughtimeError(f"{type(last).__name__}: {last}")


# ------------------------------------------------------------------ chained measurement
@dataclass
class Measurement:
    responses: List[Response]
    errors: List[Tuple[str, str]]
    violations: List[Tuple[int, int]]  # (i, j): response i (earlier) and j disagree causally

    @property
    def consistent(self) -> bool:
        return not self.violations

    def local_bound(self) -> Optional[Tuple[float, float]]:
        """Interval for (true - local) that every response allows, or None if they do not all overlap."""
        if not self.responses:
            return None
        lo = max(r.offset - r.bound for r in self.responses)
        hi = min(r.offset + r.bound for r in self.responses)
        return (lo, hi) if lo <= hi else None

    def malfeasance_report(self) -> Dict[str, object]:
        """draft-19 section 8.4.1 report: the chain of requests and responses, in order."""
        return {"responses": [
            {**({"rand": base64.b64encode(r.rand).decode()} if r.rand is not None else {}),
             "publicKey": base64.b64encode(r.public_key).decode(),
             "request": base64.b64encode(r.request).decode(),
             "response": base64.b64encode(r.response).decode()} for r in self.responses]}

    def as_dict(self) -> Dict[str, object]:
        b = self.local_bound()
        return {"responses": [r.as_dict() for r in self.responses],
                "errors": [{"server": s, "error": e} for s, e in self.errors],
                "causal_violations": [{"earlier": self.responses[i].server, "later": self.responses[j].server,
                                       "index": [i, j]} for i, j in self.violations],
                "consistent": self.consistent,
                "local_offset_interval": list(b) if b else None}


def causal_violations(responses: Sequence[Response]) -> List[Tuple[int, int]]:
    """Pairs (i, j), i received before j, with MIDP_i - RADI_i > MIDP_j + RADI_j."""
    return [(i, j) for i in range(len(responses)) for j in range(i + 1, len(responses))
            if responses[i].midp - responses[i].radi > responses[j].midp + responses[j].radi]


def measure(servers: Iterable[Server], rounds: int = 2, timeout: float = 3.0, tcp: bool = False,
            spacing: float = 0.0, rand: Callable[[int], bytes] = os.urandom,
            query_fn: Optional[Callable[..., Response]] = None, **kw) -> Measurement:
    """Query the servers in order, ``rounds`` times (two per draft-19 section 8.2), chaining nonces.

    Each nonce after the first is H(previous response || rand), so the
    responses prove their order. Failed servers are recorded and skipped.
    """
    q = query_fn or query
    seq = list(servers) * rounds
    responses: List[Response] = []
    errors: List[Tuple[str, str]] = []
    for k, s in enumerate(seq):
        if k and spacing:
            time.sleep(spacing)
        r_bytes: Optional[bytes] = None
        if responses:
            r_bytes = rand(32)
            nonce = H(responses[-1].response + r_bytes)
        else:
            nonce = rand(32)
        try:
            r = q(s, nonce=nonce, timeout=timeout, tcp=tcp, **kw)
        except RoughtimeError as exc:
            errors.append((s.name, str(exc)))
            continue
        r.rand = r_bytes
        responses.append(r)
    return Measurement(responses, errors, causal_violations(responses))


def verify_report(report: Dict[str, object]) -> List[Response]:
    """Re-check a malfeasance report: every response valid, and each nonce chained from the previous one."""
    out: List[Response] = []
    items = report.get("responses")
    if not isinstance(items, list):
        raise RoughtimeError("report has no response list")
    for k, item in enumerate(items):
        req, resp = base64.b64decode(item["request"]), base64.b64decode(item["response"])
        r = verify(req, resp, base64.b64decode(item["publicKey"]))
        if k:
            rnd = base64.b64decode(item["rand"])
            if decode(unpacket(req)).get(tag("NONC")) != H(out[-1].response + rnd):
                raise RoughtimeError(f"response {k}: nonce is not chained from response {k - 1}")
            r.rand = rnd
        out.append(r)
    return out
