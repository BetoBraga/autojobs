# v2.1 — resilient questions + Dublin profile

## Added

- 111-question/profile catalog across 10 categories.
- 43 Dublin/Ireland-recommended question definitions.
- Two run modes: Supervised and Automatic.
- Typed automatic defaults for numeric, textual and boolean fields.
- Optional social/diversity disclosure configuration with `Prefer not to say` strategy.
- Dedicated Questions tab with search, category filters and a hidden-by-default full library.
- Supervised-mode desktop maximization and blocking answer dialog for unknown required fields.
- Persisted learned answers and stable-fragment reuse.
- Locked AI tab with hover `Coming soon` / `by borerto` balloon.
- Browser-session best-effort recovery.
- React/SDUI native-value fallback when Selenium `send_keys` fails.
- Single-checkbox boolean handling and multi-checkbox `;` / `|` answer support.
- Question-system architecture documentation.
- Tests are now run before Windows PyInstaller builds and in GitHub Actions.

## Changed

- Fresh-install location defaults to `Dublin, County Dublin, Ireland`.
- Form handling is isolated per field and per job.
- Required unresolved questions skip only the current application instead of terminating the run.
- Application step safety limit increased to support longer Easy Apply forms.
- Package version bumped to 2.1.0.

## Validation in this environment

- `python -m compileall`: PASS
- `PYTHONPATH=. python -m pytest -q`: 13 passed
- Full browser/login E2E was not executed because this environment has no authenticated LinkedIn desktop session and cannot install Selenium from PyPI.
