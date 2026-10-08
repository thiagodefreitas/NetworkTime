#!/bin/sh
# SPDX-License-Identifier: MIT
# Daily step of an ntpstats validation campaign (docs/validation-campaign.md). Run from cron as root:
#   5 0 * * *  root  /usr/local/bin/campaign.sh /var/lib/ntpstats-campaign
# Moves the day's chrony logs into OUT/{refclocks,tracking,measurements}/DATE.log, lets chrony reopen
# its logs, and rewrites OUT/result.json and OUT/result.txt from the whole campaign so far.
set -eu
OUT=${1:-/var/lib/ntpstats-campaign}
LOGDIR=${CHRONY_LOGDIR:-/var/log/chrony}
NTPSTATS=${NTPSTATS:-ntpstats}
WARMUP=${WARMUP:-1h}
REF_UNCERTAINTY=${REF_UNCERTAINTY:-1e-6}
STAMP=$(date -u +%Y-%m-%dT%H%M%SZ)

for log in refclocks tracking measurements; do
    mkdir -p "$OUT/$log"
    if [ -s "$LOGDIR/$log.log" ]; then
        mv "$LOGDIR/$log.log" "$OUT/$log/$STAMP.log"
    fi
done
chronyc cyclelogs >/dev/null   # chrony keeps writing to the moved files until it reopens its logs

set -- "$OUT/refclocks" --tracking "$OUT/tracking" --measurements "$OUT/measurements" \
    --warmup "$WARMUP" --ref-uncertainty "$REF_UNCERTAINTY"
rc=0
"$NTPSTATS" validate "$@" --json > "$OUT/result.json.new" || rc=$?
"$NTPSTATS" validate "$@" > "$OUT/result.txt.new" || true
mv "$OUT/result.json.new" "$OUT/result.json"
mv "$OUT/result.txt.new" "$OUT/result.txt"
exit "$rc"   # 3 when chrony's maximum error was exceeded
