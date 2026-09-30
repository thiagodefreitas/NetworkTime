# Protocols: Roughtime, NTS pools, interleaved mode, NTPv5

ntpstats includes clients for the time protocols now being standardised or deployed, so they can
be measured next to NTP and PTP. The weekly [Live interop](INTEROP.md) workflow runs every one of
them against public servers from GitHub runners.

| Protocol | Status | In ntpstats |
|---|---|---|
| Roughtime | draft-ietf-ntp-roughtime-19 | `ntpstats roughtime`, `ntpstats.roughtime` |
| NTS pools | draft-ietf-ntp-nts-keyexchange-pool-01 | `ntpstats query --nts --pool N`, `nts.pool_sessions` |
| Interleaved mode | RFC 9769 | `ntpstats query --interleaved`, and detected in captures |
| NTPv5 | draft-ietf-ntp-ntpv5-09 | `ntpstats query --ntpv5`, `--probe-v5` |

## Roughtime: signed time and provable misbehaviour

A Roughtime server signs its time (MIDP) and a radius (RADI) with an Ed25519 key. ntpstats checks
every response:

- the delegation certificate against the server's long-term key;
- the response signature against the delegated key;
- that MIDP lies within the delegation's validity (MINT ≤ MIDP ≤ MAXT);
- the Merkle proof (PATH, INDX) that the server signed *our* request.

Servers are queried in sequence, twice, as the draft requires. Each nonce after the first is
`H(previous response ‖ random)`, so the chain of responses proves the order in which they were
received. If an earlier response's earliest possible time is later than a later response's latest
possible time (MIDP_i − RADI_i > MIDP_j + RADI_j), at least one server lied. The chain is then a
**malfeasance report** that anyone can verify.

```bash
ntpstats roughtime                                  # the bundled server list
ntpstats roughtime roughtime.se time.txryan.com --json
ntpstats roughtime --list servers.json --report malfeasance.json --check-local
ntpstats roughtime --verify-report malfeasance.json # re-check a report's signatures and chaining
```

Each line shows the signed time, its radius, and the local clock's offset with its bound
(`radius + rtt/2`). The intersection of all bounds is an **authenticated interval for the local
clock's error**. It is coarse, about a second, because Roughtime timestamps are whole seconds.
That is enough to catch a clock that NTP, PTP or GNSS has led astray: an NTP-disciplined clock
outside that interval is wrong, whatever its own statistics say. `--check-local` exits with code 3
in that case.

The server list follows the draft's JSON format (section 8.3). The bundled list comes from the
[Roughtime ecosystem list](https://github.com/cloudflare/roughtime/blob/master/ecosystem.json).
Check the keys against the operators' own publications before relying on them. Servers are
added with `host:port=BASE64KEY`.

Compatibility: ntpstats offers versions 1, draft-08, draft-11 and draft-12+ (0x8000000c).
Cloudflare's service documents draft-08 support. If a server does not answer the IETF request,
ntpstats tries once with Google-Roughtime, the pre-IETF protocol: unframed messages, 64-byte
nonces and hashes, microsecond timestamps. Some deployed servers still answer only that; in the live runs of October 2026,
Cloudflare's does. The output says which protocol answered. Chained nonces and malfeasance reports work across both. Responses in the older-draft form are
accepted too (nonce-only Merkle leaf, microsecond timestamps). The JSON output reports which form
each server used (`merkle_leaf`).

Signature checks need `cryptography`: `pip install 'ntpstats[nts]'`.

## NTS pools

With plain NTS, a client of a pool would share keys with the pool rather than with the time
server. The NTS-KE pool draft instead has the pool's key-exchange server hand out *one* server
per key exchange. A client that wants several independent sources sends **NTP Server Deny**
records naming the servers it already has. `ntpstats query --nts --pool 3 HOST` performs three
key exchanges this way and measures each assigned server with NTS:

```bash
ntpstats query srv.experimental.ntspooltest.org --nts --pool 3
```

(`srv.experimental.ntspooltest.org` is the Trifecta Tech Foundation's
[experimental pool](https://experimental.ntspooltest.org/).)

## Interleaved mode (RFC 9769)

A server can only put an estimate of its transmit time in a packet before it has sent it. In the
interleaved mode it sends the *precise* transmit time of its previous response in the next one,
often a hardware or kernel timestamp. This removes the server's transmit-path error from the
offset.

- `ntpstats query --interleaved HOST` makes two exchanges. It reports whether the server answered
  interleaved and, if it did, the offset computed with the precise timestamp.
- **Captures**: interleaved responses (origin equal to the request's receive timestamp) are
  recognised in pcap/pcapng files. Each exchange is recomputed with the precise transmit time
  from the following response and marked in the `interleaved` column. This works for chrony
  clients using `xleave`.

## NTPv5

The NTPv5 client follows draft-ietf-ntp-ntpv5-09, which is still the current draft. It covers
timescales (UTC, TAI, UT1, leap-smeared UTC), eras, cookies and the NTPv4 upgrade probe. See
[CLI](cli.md) and the [Live interop](INTEROP.md) results for which public servers answer.
