# autojobs v2.9.0

## Maximum coverage and skip-accounting release

- Split intentional pre-application filtering from Easy Apply skips: RunStats now tracks Filtered and Attempted separately and the UI shows Applied/Attempted completion.
- Added Maximize coverage preset: unlimited successful applications (`0`), result pages until exhausted (`0`), Any time, no experience/work-model narrowing, Automatic mode, no manual submit review, autonomous generic-choice fallback. Positions, locations and blacklists are preserved.
- `max_applications=0` now means unlimited and `max_pages_per_search=0` continues until exhaustion with a bounded 100-page guard and a three-pages-with-no-new-jobs stop.
- Location post-filter now blocks only high-confidence structured/dedicated conflicts. Suspicious title/company/prose values are downgraded to medium confidence and never block a job.
- Required radio/checkbox selection survives LinkedIn React/SDUI re-renders by re-locating the live choice before verification/retry.
- Required form completion gets bounded live-DOM retries before an Easy Apply attempt is skipped.
- Sensitive demographic questions never use the generic first-option fallback. Privacy-preserving options are preferred; otherwise the field remains unresolved.
- Work-authorisation/citizenship/visa questions never use generic Boolean/text fallbacks; configure factual answers in Answer Rules or answer once in Supervised mode.
- Filter reasons (previously submitted, blacklist, already applied, no Easy Apply) are now emitted to the persistent log.
- Windows build/package/installer versions updated to 2.9.0.
