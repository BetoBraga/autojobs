# Contributing to Autojobs

Thank you for helping make Autojobs more useful, understandable, and trustworthy. The project aims to support the repeated parts of a job search while leaving people in control of their own choices.

Contributions are welcome in many forms:

- Bug reports with clear, sanitized reproduction steps
- Feature ideas grounded in a real user need
- Documentation, wording, accessibility, and translation improvements
- Focused code changes with tests
- Release and Windows packaging feedback

## Before you begin

Please:

1. Read the [README](./README.md) and relevant guide before opening an issue.
2. Search existing issues so related reports can stay together.
3. Never include credentials, cookies, Chrome profile data, resumes, private application details, or sensitive personal answers in an issue, pull request, log, or screenshot.
4. Keep the project's safety boundary intact: do not contribute CAPTCHA, 2FA, challenge, rate-limit, fingerprint, stealth, or access-control bypasses.

Security reports have a separate private process. See [SECURITY.md](./SECURITY.md) instead of opening a public issue.

## Development setup

Autojobs is developed and packaged on Windows. The CI and release build target Python 3.13.

From this repository's GitHub page, use **Code** to copy the HTTPS clone command. Run it in a local folder, then use the following commands from the cloned `autojobs` folder:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe app.py
```

Google Chrome is needed for browser behavior. Do not use a real account, a real resume, or any sensitive profile data in screenshots, fixtures, or automated tests.

To create a Windows package locally, install Inno Setup 6 and run:

```powershell
.\build_windows.bat
```

The script creates the virtual environment, installs development dependencies, runs the tests, creates the portable executable, and builds the installer when Inno Setup is available.

## Making a change

1. Start from the current default branch and use a focused branch for your work.
2. Keep the change narrow and explain the user-facing reason for it.
3. Follow existing naming, formatting, and UI patterns.
4. Add or update tests when behavior changes.
5. Update documentation when users, contributors, or release steps need to know about the change.
6. Run the smallest relevant tests, then run `python -m pytest -q` before opening a pull request when practical.

LinkedIn's UI is account- and locale-dependent. A real end-to-end submission should never be required as automated test evidence. When manual browser verification is needed, describe the scenario without publishing private account data.

## Pull requests

Open a pull request when the change is ready for review. A helpful pull request:

- Explains what changed and why
- Links the issue or describes the problem it solves
- Lists automated tests and meaningful manual checks
- Calls out behavior that needs a reviewer to inspect
- Avoids unrelated refactors and generated build artifacts
- Includes only sanitized screenshots or logs

Maintainers may ask for a smaller scope, more tests, clearer documentation, or a safer alternative before merging.

## Documentation and product voice

Write in plain, respectful English. The user guide's tone is calm, practical, and encouraging:

- Explain what will happen before asking someone to act.
- Prefer clear, direct steps over unexplained jargon.
- Make limitations and risks visible rather than hiding them.
- Preserve the user's agency: they choose their answers, pace, and applications.

## License

By submitting a contribution, you agree that it may be distributed under the repository's [Apache License 2.0](./LICENSE).

## Community standards

Please follow the [Code of Conduct](./CODE_OF_CONDUCT.md) in all project spaces.
