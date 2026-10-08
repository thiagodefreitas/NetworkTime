---
description: A protocol for checking a network-disciplined clock, its daemon's error bound, its servers and every ntpstats estimator against an independent PPS reference, with chrony and ntpstats validate.
---

# Validation campaign: a real clock against an independent reference

The test suite checks ntpstats against published values, simulations and Stable32. What it cannot
check is a real client on a real network, because that needs the truth: the error of the clock at
every instant. A GNSS receiver's pulse per second (PPS) gives it to within about a microsecond,
and chrony can log that pulse against the system clock **without using it** (`noselect`). The
host then keeps synchronising over the network as usual, and the PPS records how well it does.

`ntpstats validate` turns such a campaign into four answers:

| Question | Checked against the reference |
|---|---|
| How good is the clock? | the reference series itself: bias, RMS, p95, maximum, TDEV, MTIE |
| Is the daemon's error bound honest? | every reference sample between two `tracking.log` updates must lie within the later update's maximum error, as chrony.conf(5) defines it |
| Is every server inside its correctness interval? | each measured offset θ must lie within the root distance (δ + Δ)/2 + ε + E of the true one (the correctness interval of RFC 5905 section 11.2.1, root distance of appendix A.5.5.2 without its jitter term); servers outside are falsetickers |
| Which estimator is best on real data? | every bench estimator runs on each server's exchanges (the multi-server ones on all) and is scored against the reference |

The campaign is designed so that anyone with a GNSS module and a Linux host can repeat it and send
the result in.

## Hardware

- A GNSS receiver with a PPS output. A timing receiver (u-blox M8T, F9T, LEA-M8T and similar)
  puts the pulse within tens of nanoseconds of UTC; a navigation module within about 100 ns.
  An antenna with a view of the sky; the cable delay (about 5 ns per metre) is negligible at
  this level.
- A Linux host that sees the pulse through the kernel PPS API (`/dev/pps0`):
  - Raspberry Pi: `dtoverlay=pps-gpio,gpiopin=18` in `config.txt`, PPS on GPIO 18;
  - a serial port: the PPS on DCD and `ldattach PPS /dev/ttyS0` (driver `pps_ldisc`).

  Check it with `ppstest /dev/pps0` (package `pps-tools`): one line per second.
- The reference uncertainty is then dominated by the interrupt latency of the time stamp: a few
  microseconds on a Raspberry Pi GPIO, less on a serial port or with a PHC. Pass it as
  `--ref-uncertainty` (default 1 µs).

No gpsd is needed: a PPS refclock without `lock` takes the second each pulse marks from the
system clock, and chrony's `refclock.c` accepts a pulse while the clock is synchronised with a
root distance below 0.5 s, which the network sources provide.

## chrony configuration

[`examples/validation/chrony.conf`](https://github.com/thiagodefreitas/NetworkTime/blob/master/examples/validation/chrony.conf)
contains the lines to add:

```text
# the network sources the host is disciplined by, as in production
server time.cloudflare.com iburst nts
server ptbtime1.ptb.de iburst nts
pool pool.ntp.org iburst

# the reference: logged, never selected
refclock PPS /dev/pps0 refid PPS noselect

log tracking measurements refclocks
logdir /var/log/chrony
```

After `systemctl restart chrony`, `chronyc sources` lists `#? PPS` (not selectable), never `#*`,
and `chronyc selectdata` gives it state `N` (the `noselect` option); `/var/log/chrony/refclocks.log`
gains a line per pulse. If the host already uses
the PPS for synchronisation, this is a different experiment: the reference must not be among the
selected sources.

Which column is the truth: chrony's `refclock.c` logs in the *raw* column of `refclocks.log` the
pulse against the system clock as applications read it, and in the *cooked* column the same minus
the correction chrony is still slewing out. `ntpstats validate` uses the raw column, the error an
application sees; `--cooked` selects the other.

## Running it

Let the host run for at least two weeks, so that the record spans quiet nights, busy days,
route changes and a few server incidents.
[`examples/validation/campaign.sh`](https://github.com/thiagodefreitas/NetworkTime/blob/master/examples/validation/campaign.sh),
run daily from cron, moves the day's logs into a campaign directory (one sub-directory per log),
asks chrony to reopen its logs and writes an up-to-date `result.json`:

```text
5 0 * * *  root  /usr/local/bin/campaign.sh /var/lib/ntpstats-campaign
```

The analysis on its own, at any time:

```bash
ntpstats validate campaign/refclocks --tracking campaign/tracking \
    --measurements campaign/measurements --warmup 1h --ref-uncertainty 2e-6
```

A directory is read as the concatenation of its files. The exit code is 3 when the daemon's bound
was exceeded (`--max-violation-rate` sets a tolerance), so the command can gate a CI job or an
alert. `--json` writes the full report, including the per-server statistics and every
estimator's score.

## Reading the result

- **clock error**: what the campaign measured. On a LAN with a nearby server, chrony typically
  holds tens of microseconds; over the Internet, the path asymmetry of the selected servers sets
  the bias.
- **daemon bound**: `0 outside` is the expected result. A violation means the daemon claimed more
  than it delivered in that interval, which is worth reporting to its developers with the logs.
  The line below gives how well the daemon knew its own offset at each update.
- **servers**: `bias` is the server's error plus the mean asymmetry of the path, which no client
  can separate; `in root dist.` should be 100 %. A server far below that is a falseticker, or a
  server whose path asymmetry exceeds what its delay allows, which only a broken path can do.
- **estimators**: the ranking of the bench on real exchanges. A constant asymmetry is common to
  all estimators of one server, so compare `std` within a server and `rms` across servers.

## Trying it without hardware

`ntpstats.refcheck.synthetic_campaign` writes the three logs with a known truth: a clock wandering
by tens of microseconds, three honest servers with queueing delays and a falseticker 20 ms off:

```bash
python -c "from ntpstats.refcheck import synthetic_campaign; synthetic_campaign('demo', hours=6)"
ntpstats validate demo/refclocks.log --tracking demo/tracking.log --measurements demo/measurements.log --warmup 30m
```

## Sending results

Please share `result.json` and, if you can, the logs (the server addresses are public NTP servers;
nothing else in them identifies the host) through the
[Share a sample log](https://github.com/thiagodefreitas/NetworkTime/issues/new/choose) form or in
[Discussions](https://github.com/thiagodefreitas/NetworkTime/discussions). Note the receiver,
how the PPS reaches the kernel, and the network. Results from several hosts are what turn this into
a study of how well network time actually works.
