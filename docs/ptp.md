# PTP captures and time error

## PTP from packet captures

`ntpstats` reads IEEE 1588 (PTPv2 and v2.1) messages from pcap/pcapng files. It supports UDP
over IPv4 and IPv6 (ports 319/320) and Ethernet (EtherType 0x88F7, with VLAN tags). Each
master/slave flow becomes a time series, measured from the **capture host's clock**:

```bash
ntpstats info capture.pcapng            # lists the PTP (and NTP) flows found
ntpstats stability capture.pcapng -k tdev,mtie
ntpstats network capture.pcapng         # PDV, delay floor, FPP on the path delay
```

| Quantity | How it is obtained |
|---|---|
| `t1` | Sync origin timestamp (one-step) or Follow_Up precise origin timestamp (two-step) |
| `c2`, `c3` | capture times of the Sync and of the slave's Delay_Req |
| `t4` | Delay_Resp receive timestamp |
| corrections | Sync + Follow_Up correction on master→slave; Delay_Resp correction on slave→master (IEEE 1588) |
| mean path delay | `((c2 − t1 − cf) + (t4 − c3 − cf_resp)) / 2`, from the Sync preceding each Delay_Req |
| offset | `mean_path_delay − (c2 − t1 − cf)` for every Sync (reference − local, as for NTP) |

Details:
- **Peer delay** (Pdelay_Req/Resp/Resp_Follow_Up, one- or two-step): the mean link delay is used
  instead of the mean path delay.
- **Sync only**: the series is the one-way time (offset plus delay). It still serves
  packet-delay-variation analysis.
- **Timescale**: PTP timestamps are TAI. The UTC offset comes from Announce
  (`currentUtcOffset`) or, without Announce, is inferred when the one-way times are 30–45 s.
- **Security**: messages with an AUTHENTICATION TLV (IEEE 1588-2019 annex P, as used by
  NTS4PTP) are counted in `meta["authenticated"]`. They are not verified.
- **Extra columns**: `mean_path_delay` (or `mean_link_delay`), `ms_delay`, `sm_delay`,
  `correction`, `sequence` and `authenticated`.

Capture at the slave with hardware timestamps (`tcpdump -j adapter_unsynced
--time-stamp-precision nano -w cap.pcapng`, NIC permitting), and the capture clock is the
slave's PHC. Timestamps are kept as integer nanoseconds throughout.

## NTP over PTP (RFC 10030)

[RFC 10030](https://www.rfc-editor.org/rfc/rfc10030) (chrony 4.9, `server ... ptpport 319`) carries
NTP client/server messages in an organization-specific TLV (OUI 00-00-5E, subtype 1) of unicast
PTP event messages on UDP port 319. NICs that time-stamp only PTP then time-stamp NTP, and one-step
E2E transparent clocks add their residence time to the correction field.

`ntpstats` recognises these packets in pcap/pcapng files and analyses them as NTP exchanges
(not as PTP flows). The correction of the response is in its PTP header; the correction of the
request comes back from the server in the Network Correction extension field (0x010A). When both
are present they are applied as RFC 10030 section 3 specifies:

```text
offset_c = offset + (nc_rs − nc_rq) / 2
delay_c  = delay − (nc_rs + nc_rq − dur_rs − dur_rq) × (1 − 100 ppm)
```

`nc_rs` is the response's correction plus its receive duration (frame length at 1 Gb/s), and the
request's duration is taken equal to the response's (the RFC allows this). Corrections that are
negative, or that make the delay negative, are not applied, as the RFC requires. The series keeps
`offset_uncorrected`, `delay_uncorrected`, `nc_request` and `nc_response`, and
`meta["corrected"]` counts the corrected exchanges:

```bash
ntpstats info examples/data/ntp-over-ptp.pcap      # synthetic: two transparent clocks, 600 exchanges
```

In that example the corrections bring the offset error from 10.8 µs to 2.5 ns rms.

## CSPTP (client-server PTP)

CSPTP is a client-server profile of PTP (sdoId 0x300) that ntpd-rs 2.0 and statime implement,
experimentally, as `csptp` sources. The client sends a unicast Sync with a CSPTP request TLV; the
server answers with a Sync whose response TLV carries the request's receive time and its
correction field, and the response's transmit time follows in the Sync (one-step) or a
Follow_Up (two-step). Each exchange therefore has all four timestamps, like NTP:

```text
forward  = t2 − c1 − cf_request        backward = c4 − t3 − cf_response
offset   = (forward − backward) / 2    delay    = forward + backward
```

`c1` and `c4` are the capture times of the request and response, so the offset is the server's
relative to the capture host's clock, with transparent-clock corrections removed in both
directions as statime does. When the server works on the PTP timescale (TAI) and the capture
clock on UTC, the UTC offset is inferred from the exchange timing (`meta["utc_offset_s"]`). A
CSPTP status TLV, when present, gives the grandmaster identity and steps removed. CSPTP
messages become one series per client/server pair (`meta["protocol"] == "csptp"`) and are not
mixed into the master/slave flows above.

## Time-error metrics

`ntpstats timeerror` computes the metrics used to qualify PTP clocks and packet networks, with
the definitions of ITU-T G.8260 (as used by G.8273.2). **TE = local − reference**, the opposite
sign of ntpstats offsets, which are converted automatically.

| Metric | Definition |
|---|---|
| max\|TE\| | maximum absolute time error, unfiltered |
| cTE | mean TE over the record; `--cte-window` (1000 s) gives per-window means and the worst one |
| TEL, max\|TEL\| | TE through a first-order low-pass of `--lpf-hz` (0.1 Hz) |
| dTE_L | TEL − cTE: peak-to-peak, **MTIE** and **TDEV** |
| dTE_H | TE − TEL: peak-to-peak |

The filter restarts after gaps. The first five time constants after each start (8 s at 0.1 Hz)
are left out of the filtered metrics. Sample at 1 Hz or faster, or the filter cannot separate
dTE_L from dTE_H (a warning says so).

```bash
# a PTP capture, a linuxptp log or any supported log
ntpstats timeerror capture.pcapng --limits my-limits.csv --mask dte-l-mtie.csv --mask dte-l-tdev.csv

# a time-interval counter comparing the DUT 1PPS with a reference (values in ns, DUT - REF)
ntpstats timeerror tic.csv --tau0 1 --units ns --input-is-te --json

# add a time-error section (cards and a TE/TEL chart) to the HTML report
ntpstats report capture.pcapng --time-error -o report.html
```

**Limits are your own**; no standards text ships with ntpstats. `--limits` takes `metric,value`
lines, with values in seconds or with a unit suffix:

```text
# my-limits.csv: numbers chosen for this test
max_te, 100ns
cte_window, 50ns
dte_h_pp, 70ns
```

Metrics: `max_te`, `cte`, `cte_window`, `max_tel`, `dte_l_pp`, `dte_h_pp`. `--mask` files
are the usual `tau,mtie` or `tau,tdev` masks ([Statistics](statistics.md)) and apply to dTE_L.
The exit code is 3 when any limit or mask fails, so the command fits CI pipelines. The web UI
shows them on *Comply → Time error*, with the TE/TEL chart and the MTIE and TDEV of dTE_L.

An example capture (synthetic, hardware-timestamp style, 25 minutes at 1 Hz) is in
`examples/data/ptp-capture.pcapng`.
