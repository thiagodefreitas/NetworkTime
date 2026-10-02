# Security policy

ntpstats includes network clients (SNTP, NTS, NTPv5), a local web UI and parsers for untrusted
files. Security reports are welcome and taken seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through GitHub's
[private vulnerability reporting](https://github.com/thiagodefreitas/NetworkTime/security/advisories/new).
If that form is unavailable, contact @thiagodefreitas on GitHub without disclosing details publicly.

Please include the version, how to reproduce it, and the impact you expect. You should get an
answer within a week. Fixes are released as a patch version and credited in the changelog,
unless you prefer otherwise.

## Supported versions

Security fixes go to the latest minor release of the current major series (3.x). Upgrading from
2.15 or later to 3.0 needs no code changes, so 2.x is not maintained separately.

## Scope notes

- The web UI (`ntpstats ui`) binds to 127.0.0.1 by default and checks Host headers, a CSRF
  header and a content security policy. Exposing it on other interfaces is at your own risk.
- The metrics endpoint (`--metrics-port`) binds to 127.0.0.1 by default and serves read-only data.
- NTS uses the Python `ssl` module (TLS 1.3, certificate verification on) and AES-SIV from the
  optional `cryptography` extra.
