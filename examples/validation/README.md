# Validation campaign

Files for checking a network-disciplined clock against an independent PPS reference with
`ntpstats validate`. The protocol, what each result means and how to send results in are in
[docs/validation-campaign.md](../../docs/validation-campaign.md).

| File | Purpose |
|---|---|
| `chrony.conf` | the lines to add: network sources, the PPS as a `noselect` refclock, logging |
| `campaign.sh` | daily cron step: collects the logs and rewrites `result.json` and `result.txt` |

Without hardware, try it on synthetic logs with a known truth:

```bash
python -c "from ntpstats.refcheck import synthetic_campaign; synthetic_campaign('demo', hours=6)"
ntpstats validate demo/refclocks.log --tracking demo/tracking.log --measurements demo/measurements.log --warmup 30m
```
