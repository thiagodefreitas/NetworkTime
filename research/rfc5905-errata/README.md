# RFC 5905 errata: drafts and evidence

Three places where the C code of RFC 5905's Appendix A contradicts the RFC's own normative text (as
corrected by its errata) and the reference implementation. They were found while modelling NTP's clock discipline in the ntpstats research
bench ([docs/research-bench.md](../../docs/research-bench.md)).

None of the 37 errata on record for RFC 5905 (15 verified, 17 held for document update, 2 reported,
3 rejected; checked 12 October 2026) covers them. Two are related: erratum 5600 (verified) corrected
the jitter formula in Section 10, and erratum 3 below asks for the appendix code to follow it;
erratum 6550 (verified) changed another term of the same A.5.2 loop. None of the RFCs that update
RFC 5905 (7822, 8573, 9109, 9748, 9769) touches the appendix code.

**Status:** submitted to the RFC Editor on 12 October 2026 and listed as reported:
[Errata ID 9215](https://errata.rfc-editor.org/eid9215/) (erratum 1),
[9216](https://errata.rfc-editor.org/eid9216/) (erratum 2) and
[9217](https://errata.rfc-editor.org/eid9217/) (erratum 3).

Each section below is laid out as the RFC Editor's errata form asks: section, original text,
corrected text, notes. Submit at <https://www.rfc-editor.org/errata.php>, one erratum per submission,
type **Technical** for errata 1 and 2. Erratum 3 can be Technical or Editorial.

`reproduce.py` in this directory reproduces the numbers quoted for erratum 1:

```bash
pip install ntpstats            # 3.7.0 or later
python research/rfc5905-errata/reproduce.py
```

---

## Erratum 1 (ID 9215): loop constants PLL and AVG (A.5.5.6)

**Section:** A.5.5.6

**Original Text:**

```
#define PLL             65536   /* PLL loop gain */
#define FLL             MAXPOLL + 1 /* FLL loop gain */
#define AVG             4       /* parameter averaging constant */
```

**Corrected Text:**

```
#define PLL             16      /* PLL loop gain */
#define FLL             MAXPOLL + 1 /* FLL loop gain */
#define AVG             8       /* parameter averaging constant */
```

**Notes:**

The two constants contradict the normative text. Figure 27 (Section 11.3, "Clock Discipline
Variables and Parameters") specifies "TC 16 time constant scale" and "AVG 8 averaging constant", and
Section 12 states that "the TC parameter scales the time constant to match the poll interval". The
appendix uses PLL in exactly that role: clock_adjust() (A.5.6.1) removes
c.offset / (PLL * min(LOG2D(s.poll), ALLAN)) of the residual offset per second, and local_clock()
adds offset * min(mu, LOG2D(s.poll)) / (4 * PLL * LOG2D(s.poll))^2 to the frequency. The reference
implementation agrees with Figure 27: ntpd 4.2.8, ntpd/ntp_loopfilter.c, defines CLOCK_PLL 16 and
CLOCK_AVG 8 and uses them in the same expressions. Its comment reads "PLL loop gain (log2)", which
suggests how 16 became 2^16 = 65536.

With PLL = 65536 the loop does not discipline a clock on any useful time scale. At poll 6 (64 s)
the phase time constant is 65536 * 64 s, about 48 days, instead of 16 * 64 s, about 17 minutes, and
the PLL frequency gain is smaller by (65536/16)^2, about 1.7 * 10^7. AVG = 4 instead of 8 halves the
averaging of the jitter and wander estimates (A.5.5.6) that drive the poll-interval adjustment.

Closed-loop simulation of the appendix code (noise-free reference measured every 64 s, poll fixed at
6; reproducible with research/rfc5905-errata/reproduce.py in
https://github.com/thiagodefreitas/NetworkTime):

| Loop | 10 ms phase step: below 1 ms after | 10 ppm frequency step: error after 10 h |
|---|---|---|
| Appendix as printed (PLL 65536, AVG 4) | not within 12 h; still 9.91 ms after 10 h | 85.7 ms, growing |
| Appendix with PLL 16, AVG 8 | 34 min | 1.07 ms |
| ntpd 4.2.8 | 34 min | 1.07 ms |

With the two constants of Figure 27, the appendix loop reproduces the reference implementation's
step responses; as printed, it absorbs almost none of a phase step and cannot follow a frequency
offset.

---

## Erratum 2 (ID 9216): popcorn spike suppressor compares seconds with a poll exponent (A.5.2)

**Section:** A.5.2

**Original Text:**

```
        if (fabs(p->offset - dtemp) > SGATE * p->jitter && (f[0].t -
            p->t) < 2 * s.poll)
                return;
```

**Corrected Text:**

```
        if (fabs(p->offset - dtemp) > SGATE * p->jitter && (f[0].t -
            p->t) < 2 * LOG2D(s.poll))
                return;
```

**Notes:**

f[0].t - p->t is a time difference in seconds, but s.poll is the poll exponent (log2 of the poll
interval in seconds). Section 4 defines "a poll interval of 2^tau seconds, as determined by the poll
exponent tau", the appendix defines MINPOLL 6 as "(64 s)" and MAXPOLL 17 as "(36.4 h)", poll_update()
changes s.poll with s.poll++ and s.poll--, and every other use of s.poll as a duration in the appendix
converts it first: LOG2D(s.poll) in A.5.5.6 (local_clock()), A.5.6.1 (clock_adjust()) and the
distance threshold MAXDIST + PHI * LOG2D(s.poll).

The comment directly above the test states the intent: "if the interval since the last offset is
less than twice the system poll interval, dump the spike". The reference implementation does that:
ntpd 4.2.8, ntpd/ntp_proto.c, clock_filter(), compares
peer->filter_epoch[k] - peer->epoch < 2. * ULOGTOD(peer->hpoll), twice the poll interval in seconds.

As printed, the window is 12 s instead of 128 s at poll 6, and 34 s instead of about 73 h at poll 17.
Outside a burst, successive samples are at least one poll interval (64 s or more) apart, so the
suppressor as printed can act only between packets of the same burst (BCOUNT packets two seconds
apart, Section 13.2), never across polls as the comment and the reference implementation intend.

---

## Erratum 3 (ID 9217): jitter computed without averaging in A.5.2

**Section:** A.5.2

**Original Text:**

```
        p->jitter = max(SQRT(p->jitter), LOG2D(s.precision));
```

**Corrected Text:**

```
        p->jitter = max(SQRT(p->jitter / (NSTAGE - 1)),
            LOG2D(s.precision));
```

**Notes:**

Section 10 defines the peer jitter psi as "the RMS average" of the offset differences
theta_0 - theta_j over the n - 1 other stages, and verified erratum 5600 corrected its formula so that
1/(n-1) is inside the square root. The code skeleton in A.5.2 still takes the square root of the sum
of squares without dividing by n - 1 (verified erratum 6550 corrected the dispersion term of the
same loop and left this line unchanged), so the code does not implement the corrected Section 10.
The reference implementation computes the RMS: ntpd 4.2.8, ntpd/ntp_proto.c, clock_filter(), divides
the sum by m - 1, the number of valid stages less one, before the square root. With eight stages the
code as printed gives a jitter sqrt(7), about 2.6, times the RMS. The peer jitter enters the popcorn
gate (SGATE * p->jitter, A.5.2), the cluster algorithm (A.5.5.1), the root distance (root_dist(),
A.5.5.2) and the system jitter (clock_update(), A.5.5.4), so all of them are inflated by that factor.
The correction divides by NSTAGE - 1, consistent with the appendix, which fills all NSTAGE stages;
counting only valid stages, as ntpd does, would match the reference implementation exactly.
