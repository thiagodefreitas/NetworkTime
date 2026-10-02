---
title: 'ntpstats: validating, evaluating and studying network time synchronisation'
tags:
  - Python
  - time synchronization
  - NTP
  - PTP
  - frequency stability
  - Allan deviation
  - time error
authors:
  - name: Thiago de Freitas
    # orcid: add before submission
    affiliation: 1
affiliations:
  - name: To be completed before submission
    index: 1
date: 2 October 2026
bibliography: paper.bib
---

# Summary

Computers, telecom networks, financial markets and power grids keep their clocks in step over
packet networks with the Network Time Protocol (NTP) [@rfc5905], its authenticated form NTS
[@rfc8915] and the Precision Time Protocol (PTP) [@ieee1588]. How well they do it is a
measurement question: how far is this clock from UTC, how stable is it, how much error does the
network add, and would a different algorithm do better? `ntpstats` answers these questions from
the data people already have. It reads the logs of today's time daemons (ntpd, NTPsec, chrony,
linuxptp), packet captures of NTP and PTP, GNSS time-transfer and laboratory files, and the
results of network simulators, and turns them into the statistics used in timing research and
in telecom standards, each with a stated uncertainty. It runs as a command-line tool, a Python
library with a stable API, a local web interface and, through WebAssembly, in the browser
without installation.

# Statement of need

The tools for this work are fragmented. Frequency-stability analysis is done in Stable32,
TimeLab or the `allantools` Python package [@allantools], which work on clean phase records rather
than on daemon logs and captures. Time daemons report their own state but do not evaluate it.
PTP time error is measured with vendor instruments and their proprietary software. Researchers
proposing synchronisation algorithms build one-off simulators, so results are hard to compare.
`ntpstats` puts these steps in one open, dependency-light package (numpy is its only runtime
dependency), so that an engineer certifying a deployment and a researcher evaluating an
algorithm use the same definitions and can check each other's numbers.

The intended users are:

- operators of NTP, NTS and PTP services, who need statistics, alerts and evidence;
- telecom and PTP engineers, who need time-error metrics (max|TE|, cTE, dTE, MTIE and TDEV of
  dTE as defined in ITU-T G.8260 [@g8260]) from captures and instrument exports;
- regulated users, who need a defensible error bound to UTC and an archivable report;
- metrologists and researchers, who need validated statistics, noise models, public datasets
  and a reproducible test bench.

# Functionality

**Statistics.** Overlapping and modified Allan, time, Hadamard, total, Theo and MTIE
deviations, with confidence intervals from the exact equivalent degrees of freedom of the
discrete power-law model [@greenhall2003] and per-τ noise identification from the lag-1
autocorrelation [@riley2004]. Irregular logs are placed on a grid without interpolating across
gaps. Further analyses fit the power-law noise model with bootstrap intervals, compute spectra,
separate the noise of three or more clocks with the N-cornered hat, and predict holdover.

**Network and time error.** Delay floor, the offset-versus-delay wedge, floor packet percentage
and per-direction one-way delays; time-error metrics for PTP captures with limits and masks; a
UTC traceability audit that states its assumptions; and change detection for steps, frequency
changes and route changes.

**Measurement.** NTPv4, NTS, experimental NTPv5 and Roughtime clients, used in a monthly
interoperability run against public servers whose results are published as an open dataset.

**Research bench.** A simulator with ground truth, built on power-law noise generation
[@kasdin1992], scores pluggable estimators: Kalman and RTS filters, the NTP clock filter and
combining algorithms [@rfc5905], chrony-style regression, a feed-forward estimator, and a
Huygens-style convex-hull estimator [@geng2018]. Scenarios can replay the delays of a real
capture or log under a simulated clock, and a PTP module simulates chains of boundary clocks
with linuxptp-style servos against time-error budgets. Result files of the OMNeT++/INET and ns-3
network simulators can be read and written, so the same metrics apply to simulated and measured
networks.

# Validation

Correctness is checked rather than assumed. The statistics reproduce the published test suites
of NIST SP 1065 [@riley2008] to the seven digits printed there, and the equivalent degrees of
freedom are compared with the approximations of the same handbook. Parsers are tested with lines
taken from each implementation's documentation, simulator round trips test the trace
extraction, and a frozen snapshot of the public API guards compatibility. The test suite,
executable notebooks and a browser test of the web interface run in continuous integration on
every change.

# Acknowledgements

`ntpstats` began as a Google Summer of Code 2012 project for the NTP Project of the Network Time
Foundation.

# References
