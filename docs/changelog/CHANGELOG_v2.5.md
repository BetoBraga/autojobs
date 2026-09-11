# autojobs v2.5.0

Stability and usability release driven by a real application-results log.

## Search correctness
- Added strict post-open location validation so a Dublin-only run does not process Portugal or other mismatched locations leaked by LinkedIn search.
- Added structured JobPosting metadata fallback for title, company and location extraction.

## Easy Apply answer engine
- Form scanning is now scoped to the active Easy Apply dialog/form, including open SDUI shadow DOM.
- Supervised mode prompts for every unresolved visible application question, not only controls exposing HTML `required`.
- Portuguese/common European Yes/No values are normalized to the exact LinkedIn choice.
- Portuguese social/diversity wording is recognized for privacy fallback handling.
- Custom exact questions and Learned Answers now share one reliable editor and preserve the original display label.
- Localized Next/Continue/Review/Submit actions are supported.
- Saved-draft and LinkedIn safety-reminder interstitials are handled separately from application steps.
- Text/number writes are verified after WebDriver/React events; a field that did not retain the requested value is no longer treated as successfully answered.
- Saved/profile answers that no longer match a live select/radio/autocomplete get one bounded Supervised retry using the current LinkedIn choices.
- Failure reasons in applications.csv include the unresolved question when available, making results useful for diagnosis.

## Loop / browser stability
- Added form-state fingerprints and bounded same-step stall detection.
- Browser disconnect/window-close errors are treated as recoverable infrastructure events rather than duplicate failed applications.
- Step-level status logging keeps the failsafe informed during active work.

## Desktop UX
- Responsive layout stacks Search/Behavior cards and question panes on narrower windows.
- Added a persistent configuration warning at the top.
- Added top-right Help & Troubleshooting center.
- Onboarding now highlights the corresponding live area of the main app on each step.
- AI answer import has a hover walkthrough for non-technical users.
- prompt.txt requests a ready `import_me_on_autojobs.json` file.
- Credits are fully English; `by roberto` is a subtle clickable signature at the end.

## Diagnostics
- Added persistent `autojobs.log` with a 100 MB self-reset cap.
