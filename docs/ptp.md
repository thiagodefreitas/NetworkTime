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
shows the same metrics as cards on the Overview tab.

An example capture (synthetic, hardware-timestamp style, 25 minutes at 1 Hz) is in
`examples/data/ptp-capture.pcapng`.
