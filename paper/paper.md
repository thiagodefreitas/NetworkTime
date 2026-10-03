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
    orcid: 0009-0006-7749-1401
    affiliation: 1
affiliations:
  - name: Independent researcher
    index: 1
date: 3 October 2026
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

Evaluating network time synchronisation means joining steps that today live in separate tools:
reading what a daemon or a capture recorded, turning it into a clean offset or phase series,
computing stability and time-error statistics with honest uncertainties, and comparing the
result with a limit or with another algorithm. Each step is usually done with ad hoc scripts,
so two groups analysing the same deployment, or two papers proposing synchronisation
algorithms, rarely use the same definitions or test conditions, and their numbers are hard to
check against each other.

`ntpstats` puts these steps in one open, dependency-light package (numpy is its only runtime
dependency), so that an engineer certifying a deployment and a researcher evaluating an
algorithm use the same validated statistics. Its intended users are:

- operators of NTP, NTS and PTP services, who need statistics, alerts and evidence;
- telecom and PTP engineers, who need time-error metrics (max|TE|, cTE, dTE, MTIE and TDEV of
  dTE as defined in ITU-T G.8260 [@g8260]) from captures and instrument exports;
- regulated users, who need a defensible error bound to UTC and an archivable report;
- metrologists and researchers, who need validated statistics, noise models, open data and a
  reproducible test bench for clock-synchronisation algorithms.

# State of the field

Frequency-stability analysis is well served for clean phase or frequency records. Stable32
[@stable32] and TimeLab [@timelab] are the reference desktop programs of the time and frequency
community, and `allantools` [@allantools] provides the classical deviations in Python. None of
them reads daemon logs or packet captures, and they do not address network effects (delay
asymmetry, path changes) or the time-error metrics of packet-network standards. Time daemons
come with monitoring of their own state, and NTPsec's `ntpviz` [@ntpviz] plots ntpd statistics
files, but they report rather than evaluate: they give no confidence intervals, no limits and no
comparison between algorithms. PTP time error is mostly measured with vendor instruments and
their proprietary analysis software. On the research side, OMNeT++/INET [@omnetpp] and ns-3
[@ns3] simulate networks, and papers on synchronisation algorithms such as Huygens
[@geng2018] usually come with one-off evaluation code.

`ntpstats` does not replace these tools; it connects them. It reads and writes Stable32
files (plain phase and frequency files that TimeLab also imports), offers an `allantools`-compatible interface, and reads and
writes OMNeT++ and ns-3 result files, so data can move between them. Contributing to an existing
project was considered, but the missing parts (log and capture parsers, network and time-error
metrics, a ground-truth simulator and an estimator benchmark) are outside the scope of the
stability libraries and of the daemons, and they share one data model that is easier to keep
consistent in a single package.

# Software design

Every input becomes a `TimeSeries`: POSIX timestamps, offsets in seconds and per-sample extra
columns such as delay or dispersion, plus metadata. Parsers register in a table, input formats
are detected from content, and third-party packages can add parsers, estimators and detectors
through Python entry points without changing `ntpstats`. Text logs larger than 256 MB are read
in blocks with bounded memory.

The statistics follow NIST SP 1065 [@riley2008]: overlapping and modified Allan, time, Hadamard,
total, Theo and MTIE deviations, with confidence intervals from the exact equivalent degrees of
freedom of the discrete power-law model [@greenhall2003] and per-τ noise identification from the
lag-1 autocorrelation [@riley2004]. Irregular logs are placed on a grid without interpolating
across gaps, because interpolation would invent the very noise being measured. Further modules
fit the power-law noise model with bootstrap intervals, compute spectra, separate the noise of
three or more clocks with the N-cornered hat, predict holdover, compute time-error metrics with
limits and masks, produce a UTC traceability audit that states its assumptions, and detect steps,
frequency changes and route changes.

The research bench separates three parts: a simulator with ground truth built on power-law noise
generation [@kasdin1992]; an estimator interface with reference implementations (Kalman and RTS
filters, the NTP clock filter and combining algorithms [@rfc5905], chrony-style regression, a
feed-forward estimator and a Huygens-style convex-hull estimator [@geng2018]); and a scorer that
reports error statistics for every estimator on the same scenarios. Scenarios can replay the
per-direction delays extracted from a real capture under a simulated clock, and a PTP module
simulates chains of boundary clocks with linuxptp-style servos against time-error budgets.
Simulations are seeded, so a benchmark is reproducible from its scenario file.

Three trade-offs shaped the design. Depending only on numpy keeps the package installable
everywhere, including in the browser through Pyodide, at the cost of writing some numerical
code that larger libraries would provide; pandas, xarray and Parquet support are optional
extras. The web interface is plain JavaScript with one bundled charting library and no build
step, served by the Python standard library, so it can be audited and works offline. Finally,
the public API is a single flat module whose surface is frozen in a snapshot that continuous
integration checks; names change only after a deprecation period, so scripts and notebooks
written for a paper keep working.

# Research impact statement

`ntpstats` is designed to make results in network time synchronisation reproducible and
comparable. Concretely, it provides:

- statistics that reproduce the published test suites of NIST SP 1065 [@riley2008] to the seven
  digits printed there, so values can be cited with confidence;
- an open dataset: a monthly interoperability run from GitHub-hosted runners measures public
  NTP, NTS, NTPv5 and Roughtime servers, and each release, archived on Zenodo with this data, is
  citable;
- a benchmark in which a new estimator is compared with reference algorithms on the same
  simulated and replayed scenarios, with ground truth;
- executable notebooks that run in continuous integration and serve as worked examples.

<!-- Before submission, add concrete evidence of use here: studies, theses, operational
deployments, courses or citations that used ntpstats, and links to them. JOSS reviewers look
for this. -->

# AI usage disclosure

<!-- To be written by the author before submission. JOSS asks which generative AI tools were
used, for what (code, tests, documentation, this paper) and how their output was reviewed and
validated; the author confirms responsibility for the submitted work. -->

*To be completed by the author.*

# Acknowledgements

`ntpstats` began as a Google Summer of Code 2012 project for the NTP Project of the Network Time
Foundation.

# References
