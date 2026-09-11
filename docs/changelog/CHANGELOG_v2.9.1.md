# autojobs v2.9.1

## Maximum coverage follow-up

- Location is now a LinkedIn search scope by default, not a post-open application gate.
- Added `post_open_location_filter` as an explicit opt-in guard; the legacy `strict_location_filter` value is forced off during normalization so an old config cannot silently re-enable location blocking on upgrade.
- Maximize coverage always disables post-open location rejection.
- New default action delay is 3-7 seconds.
- Added an inline aggressive-delay warning plus a pre-run confirmation when the configured cadence is unusually fast.
- Warning text explicitly notes that LinkedIn publishes no guaranteed safe interval and that fast unattended activity may increase throttling/challenge/temporary-restriction risk.
- Maximize coverage raises overly aggressive delays to at least the conservative 3-7 second baseline.
- Help and user documentation updated for the new location and delay behavior.
- Preserves v2.9.0 coverage accounting, required-control retries, radio/checkbox re-location, sensitive-question safeguards, factual work-authorisation handling, and unlimited/exhaust-search options.
