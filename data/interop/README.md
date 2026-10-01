# ntpstats open interop dataset

Monthly measurements of public NTP, NTS, NTS-pool, NTPv5 and Roughtime servers, taken by the
[Live interop](../../.github/workflows/interop.yml) workflow from GitHub-hosted runners over
IPv4. The first scheduled run of each month (the workflow runs weekly) is written to
`YYYY/YYYY-MM-DD.jsonl`, one JSON object per probe (about 12 KB per run). Each ntpstats
release is archived on Zenodo together with this directory, so every version of the dataset is
citable (see `CITATION.cff`).

```bash
ntpstats info data/interop --all-peers                       # one series per test and server
ntpstats stability data/interop --peer time.google.com -k oadev
```

```python
from ntpstats import load
for s in load("data/interop"):
    print(s.meta["test"], s.meta["peer"], f"{s.meta['availability']:.0%}", len(s))
```

## Record schema (version 1)

| Field | Meaning |
|---|---|
| `schema` | record format version (1) |
| `run` | start of the run, UTC ISO 8601 |
| `time` | time of the probe, POSIX seconds (runner clock) |
| `ntpstats`, `runner`, `family` | software version, runner image, address family |
| `test` | `ntp4`, `interleaved`, `nts`, `ntpv5`, `nts-pool`, `roughtime`, `roughtime-chain` |
| `server` | name queried (for `nts-pool`, the pool; `ntp_server` is the server it assigned) |
| `ok`, `error` | outcome; `error` holds the message of a failed probe |
| `offset`, `delay` | server − runner clock and round-trip delay, seconds (Roughtime: MIDP − local midpoint, rtt) |
| `address`, `stratum`, `refid`, `root_delay`, `root_dispersion`, `leap`, `version` | from the NTP response |
| `interleaved` | RFC 9769: the server answered in interleaved mode |
| `offers_v5`, `timescale`, `draft` | NTPv5 upgrade probe and v5 response |
| `ntp_server`, `cookies_left`, `denied`, `session` | NTS and NTS-pool details |
| `midp`, `radius`, `merkle_leaf`, `protocol` | Roughtime signed time, radius (s), Merkle-leaf form, `ietf` or `google` (pre-IETF protocol) |
| `responses`, `violations`, `local_offset_interval` | Roughtime chain summary |

Caveats:
- The runner's clock is not a reference. Offsets mix server error, the runner's clock error and
  path asymmetry; they are useful for availability, protocol support and gross errors, not for
  sub-millisecond accuracy.
- Runners change between runs (the `address` and `runner` fields help).
- Each server receives only a few packets per week; one run per month is recorded.

The data are released under the repository's MIT license.
