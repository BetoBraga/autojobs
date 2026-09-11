# v2.2 — friendlier UI, portable answer profiles, headless Chrome

## Added

- Redesigned three-step desktop workflow: Search & Browser → Answer Rules → Run.
- Split Answer Rules editor with searchable question library and inline selected-answer editor.
- Question scopes: Dublin essentials, Configured only, Social & diversity, All questions.
- Configured/learned answer counters.
- Versioned Answer Profile JSON export.
- Answer Profile JSON import with Merge and Replace modes.
- JSON compatibility with answer fields from a full application config.
- Explicit warning that exported answer profiles may contain configured sensitive/social answers.
- Persistent `headless_browser` setting in desktop and CLI configuration.
- Chrome `--headless=new` with fixed 1920×1080 viewport.
- Headless authentication guard: headless mode never waits invisibly for manual login/2FA.
- Visible-login workflow that always opens normal Chrome even when headless execution is enabled.
- Header summary showing run mode + browser mode.
- Numeric fallback validation/normalization and boolean default normalization.

## Changed

- Setup renamed to Search & Browser and simplified into session/files, search, and automation cards.
- Questions renamed to Answer Rules.
- Dublin question library no longer requires a separate “show full library” checkbox; scope filtering is explicit.
- Configuring a catalog answer no longer requires a modal for every row; answers are edited in the right-side panel.
- Import/export controls are also exposed from Learned Answers for discoverability.
- Package version bumped to 2.2.0.

## Fixed

- Removed a duplicate answer prompt in the manual learned-answer editor.
- Invalid numeric fallback text no longer silently reaches number inputs from the desktop UI.
- Headless runs with an expired/missing login session stop safely instead of waiting forever for an invisible login screen.

## Validation

- Python compile checks: PASS.
- Automated suite: 18 passed.
- Tk/ttk GUI construction smoke test under a virtual display: PASS.
