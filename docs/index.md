# ntpstats

**Validate, evaluate and study network time synchronisation.**

ntpstats reads the logs of today's time daemons (ntpd 4.2.8, NTPsec, chrony, linuxptp), packet
captures and CSV. It measures servers with NTPv4, NTS and experimental NTPv5 clients, and
computes the offset, delay and frequency-stability statistics used in timing research and
telecom standards, with confidence intervals and noise identification. A simulator with ground
truth and a pluggable estimator API turn it into a test bench for synchronisation algorithms.

![Offset view](img/ui-offset-light.png)

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | install, the web UI, first analyses |
| [CLI reference](cli.md) | every command and its options |
| [Formats](formats.md) | supported inputs, sign conventions, how to enable the logs |
| [Statistics](statistics.md) | ADEV … TheoH, EDF and confidence intervals, masks, dynamic views |
| [Network and estimators](network.md) | delay floor, wedge, FPP, filters, the research bench |
| [Validation](validation.md) | how correctness is established, and how to validate your own setup |
| [API reference](api/index.md) | Python API, generated from the source |
| [Live interop](INTEROP.md) | results against public NTP/NTS servers |
| [State of the art](STATE_OF_THE_ART.md) | NTP in 2026 and a review of the 2012 prototype |

ntpstats is MIT-licensed, © 2012–2026 Thiago de Freitas. The only runtime dependency is numpy;
matplotlib (static figures) and pyOpenSSL/cryptography (NTS) are optional extras.
