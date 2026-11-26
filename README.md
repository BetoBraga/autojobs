<p align="center">
  <img width="220" src="assets/logo-autojobs.png" alt="Autojobs logo">
</p>

<h1 align="center">Autojobs</h1>

<p align="center">
  <strong>Make a little more room for your next step.</strong><br>
  A local, open-source desktop companion for the repeated parts of LinkedIn Easy Apply.
</p>

<p align="center">
  <a href="../../releases">
    <img src="https://img.shields.io/badge/download-Windows%20release-2563EB?style=for-the-badge&amp;logo=windows&amp;logoColor=white" alt="Download the Windows release">
  </a>
  <a href="./LICENSE">
    <img src="https://img.shields.io/badge/open%20source-Apache%202.0-0F766E?style=for-the-badge" alt="Apache 2.0 license">
  </a>
  <a href="../../actions/workflows/build-windows.yml">
    <img src="../../actions/workflows/build-windows.yml/badge.svg" alt="Windows build status">
  </a>
</p>

<p align="center">
  <a href="#installation"><strong>Get Autojobs</strong></a>
  <span aria-hidden="true"> | </span>
  <a href="#your-first-run"><strong>Start your first run</strong></a>
  <span aria-hidden="true"> | </span>
  <a href="#contributing"><strong>Contribute</strong></a>
  <span aria-hidden="true"> | </span>
  <a href="#feedback-and-support"><strong>Share feedback</strong></a>
</p>

> [!IMPORTANT]
> Autojobs supports repetitive Easy Apply work. It does **not** bypass CAPTCHA, 2FA, account challenges, access controls, or other anti-abuse measures. You sign in directly, choose what is true for you, and remain responsible for your use of LinkedIn and its policies.

---

### A more deliberate way to move through repetitive work

Autojobs is a Windows desktop app that helps you search, prepare answers, and work through supported LinkedIn Easy Apply steps without losing your place in the process. It is built around one simple idea: the repeated work can feel lighter, while your choices, voice, and next step remain your own.

**Contributions, testing, documentation improvements, and thoughtful feedback are welcome.**

## What is Autojobs?

Autojobs brings a clear, local-first workflow to a job search:

| Set your direction | Share what is true | Choose your pace | Look back clearly |
| --- | --- | --- | --- |
| Select roles, locations, documents, and filters that fit your search. | Create reusable answer rules and keep personal decisions in your hands. | Start in Guided mode, then use Automatic mode when you are ready. | Review local outcomes, progress, and diagnostic information in one place. |

It is designed for people who want less friction in repetitive application work, not less agency.

## Core features

### A search that follows your direction

Set job titles, resume or CV, locations, date ranges, experience levels, work types, and blacklists from one desktop screen. Search scopes can be a city, country, region, `Remote`, or `Worldwide`, and you can add one scope per line for separate searches.

### Answer rules that stay truthful

Use **Answer Rules** to create reusable answers, save responses learned in Guided mode, and export a portable JSON backup. The app can help with supported form controls, but important facts remain yours to decide. Work authorization, citizenship, visa, and sensitive demographic facts are never fabricated.

### Guided first, automatic when ready

**Guided mode** pauses when a new visible question needs your input, then can remember your answer locally for a similar question later. **Automatic mode** is available for answer rules you have already reviewed and includes configurable behavior for unknown choice controls.

### A run you can see, pause, and stop

Follow the current job, counters, progress, and plain-language status from the **Run** screen. Stop safely after the current browser operation. If the workflow goes silent past the configured failsafe time, Autojobs offers recovery, a visible Guided restart, waiting, or stopping.

### Local data and portable customization

Autojobs uses a dedicated local Chrome profile instead of storing or typing a LinkedIn password. Your application history, logs, settings, and failsafe reports stay on your computer. Themes and answer profiles are portable, editable files.

## Everything included

### Search and browser workflow

- Job-title, location, date, experience-level, and work-type filters
- City, country, regional, remote, and worldwide search scopes
- Dedicated local Chrome profile with manual, visible LinkedIn login
- Optional Chrome background mode after a valid session exists
- Resume and cover-letter selection
- Configurable action delays, application limits, and result-page limits
- Blacklists for companies and job titles

### Answer profiles and form support

- Reusable question-answer rules
- Guided prompts for unresolved visible Easy Apply questions
- Locally remembered answers for similar questions
- Answer-profile JSON export and import with Merge or Replace options
- AI-ready [`prompt.txt`](./prompt.txt) for conservatively preparing an import profile from a resume or CV
- Support for text, number, select, radio, checkbox, and autocomplete-style controls
- Language-agnostic structural form handling with current and legacy Easy Apply fallbacks

### Visibility, recovery, and records

- Guided and Automatic run modes
- Optional submission review before an application is sent
- Applied, attempted, skipped, failed, and filtered outcome tracking
- Searchable local application history with safe LinkedIn links
- Capped local `autojobs.log` diagnostic log
- Configurable failsafe with a local diagnostic report
- Safe stopping while a browser action is in progress

### Packaging and personalization

- Per-user Windows installer
- Portable Windows package
- No Python required to use a released build
- Editable [`themes.json`](./themes.json) with safe built-in fallbacks
- Reproducible Windows packaging through PyInstaller, Inno Setup, and GitHub Actions

---

## Installation

### Download a Windows build

Prebuilt Windows releases are published on the [Releases page](../../releases).

| Option | Best for | What to do |
| --- | --- | --- |
| **`autojobs-Setup.exe`** | Most people | Download it, run it, follow the onboarding prompts, and launch Autojobs from the Start menu or optional Desktop shortcut. |
| **Portable ZIP** | A movable, no-install folder | Extract the whole ZIP to a normal folder and double-click `autojobs.exe`. Do not run it from the ZIP preview. |

The installer is per-user and normally does not need administrator access.

For the portable package, keep these files together:

```text
autojobs.exe
themes.json
README.txt
prompt.txt
answer-profile-template.json
```

Python is not required for either released option.

### Build from source

#### Prerequisites

- Windows 10 or Windows 11
- Python 3.13
- Google Chrome
- Inno Setup 6, only when you also want to create `autojobs-Setup.exe`

From this repository's GitHub page, use **Code** to copy the HTTPS clone command. Run it in a local folder, then use the following commands from the cloned `autojobs` folder:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe app.py
```

To create the portable executable and run the release build workflow:

```powershell
.\build_windows.bat
```

The build script creates the virtual environment, installs development dependencies, runs the test suite, produces `dist\autojobs.exe`, and creates `installer-output\autojobs-Setup.exe` when Inno Setup 6 is available.

## System requirements

| Requirement | Details |
| --- | --- |
| **Operating system** | Windows 10 or Windows 11 |
| **Browser** | Google Chrome |
| **Account** | A LinkedIn account that you sign in to directly |
| **Documents** | A current resume or CV; a cover letter is optional |
| **Network** | Internet access for LinkedIn and potentially the first compatible ChromeDriver resolution |
| **For released builds** | Python is not required |
| **For source builds** | Python 3.13; Inno Setup 6 is optional for the installer |

> [!TIP]
> Chrome login is always visible. Background mode only applies after a valid LinkedIn session exists and a search or application run has started. Keep the computer awake and connected while a run is active; it cannot continue through sleep or hibernation.

---

## Your first run

### 1. Set your direction

Open **1. Search**, choose your resume or CV, add job titles, set search locations, and select any filters that matter to you.

Click **Open LinkedIn login**. Chrome opens visibly so you can sign in normally and complete your password, 2FA, CAPTCHA, or account checks yourself. Once Autojobs sees a valid session, it can reuse its dedicated local Chrome profile later.

### 2. Set answer rules you trust

Open **2. Answer Rules** to add reusable answers and choose conservative fallback behavior. You can export an answer profile as JSON, or import one with Merge or Replace behavior.

To prepare an initial profile more quickly, upload your resume or CV and [`prompt.txt`](./prompt.txt) to an AI assistant, download the generated `import_me_on_autojobs.json`, then choose **Import answers...**. Review meaningful answers before running. The included prompt tells the AI not to invent legal, sensitive, or unsupported facts.

### 3. Start in Guided mode

Open **3. Run** and choose **Start with guidance** for your first session. If a visible Easy Apply question is unresolved, Autojobs pauses so you can answer it. It can keep that answer locally for a future similar question.

| Mode | Best for | Behavior |
| --- | --- | --- |
| **Guided** | First runs and new question types | Pauses for your answer or confirmation when needed. |
| **Automatic** | Reviewed answer rules and familiar workflows | Does not ask for unknown questions; it follows the fallback choices you configured. |

Automatic mode does not invent work authorization, citizenship, visa, or sensitive demographic facts. Configure facts you know are true before relying on an unattended run.

### 4. Stay in control

- Use **Stop** to ask the worker to finish safely after its current browser operation.
- Monitor current job, counters, status, progress, and local logs from the Run screen.
- Use the default 60-second **Failsafe Time**, or choose a value from 15 to 900 seconds.
- When a run goes silent for the failsafe period, choose to restart visibly in Guided mode, try recovery, wait, or stop.
- Review outcomes in **Applied**, which separates intentional filtering from attempted applications that applied, skipped, or failed.

---

### Before sharing a bug report

- Complete login and account checks yourself. Keep the browser session and your application decisions under your control.
- Review saved answers before using them; do not reuse an answer whose context or wording changed.
- Keep the dedicated browser profile and the full runtime folder private. If you request support, share only the minimum redacted excerpt needed to reproduce the issue. Remove names, contact details, account identifiers, application answers, and local paths from logs or screenshots.

## Privacy, limitations, and safe use

### Your data stays close to you

Autojobs stores runtime data in `%APPDATA%\autojobs`, including settings, its dedicated Chrome profile, `applications.csv`, `autojobs.log`, and failsafe reports. Treat this folder as private because a signed-in browser profile can be sensitive.

Answer-profile JSON exports include answer rules and fallback settings. They do **not** include your Chrome session, resume or CV contents, application history, job-search settings, or local file paths. Answers can still be personal, so store exported JSON files thoughtfully.

### Important limitations

- LinkedIn can change its UI, available questions, and account-specific flow at any time.
- Not every job result is Easy Apply, and some applications require facts that should only come from you.
- Autojobs does not promise a particular application volume, response rate, or account outcome.
- LinkedIn may restrict accounts that use third-party automation. Choose a pace that feels right for you and understand that account risk.
- A low action delay can increase the likelihood of throttling, challenges, or temporary restrictions. For long unattended runs, Autojobs uses a conservative 3-7 second baseline, not a guarantee.

### Make your first run easier

- Start with Guided mode and a small search scope.
- Review answer rules, especially work eligibility and personal questions.
- Keep Chrome and Autojobs open, but do not need to keep Chrome in the foreground.
- Use a normal, awake Windows session with a stable internet connection.
- Share only sanitized logs or screenshots if you ask for help.

## How it works

1. **You configure the search.** Autojobs turns your roles, locations, and selected filters into LinkedIn search scopes.
2. **You sign in visibly.** Chrome opens for you to complete login and every security step directly.
3. **Autojobs works through supported forms.** It uses form structure, control semantics, saved answers, and validated selections before relying on display text alone.
4. **You retain the decision points.** Guided mode asks when it needs you; Automatic mode stays within the answer rules and fallback behavior you chose.
5. **The app records outcomes locally.** Application results, status, and diagnostics remain available for review on your computer.

## Documentation

- [Documentation index](./docs/README.md) -- a structured map of user, reference, changelog, and validation documentation.
- [Plain-language offline guide](./README.txt) -- installation, onboarding, troubleshooting, and everyday use. It remains at the root for portable Windows builds.
- [Automation Guide PDF](<./docs/user-guide/Autojobs Automation User Guide.pdf>) -- a visual guide for a calmer first run.
- [Answer profile format](./docs/reference/ANSWER_PROFILE_FORMAT.md) -- the JSON schema, import behavior, and privacy boundary.
- [Question system notes](./docs/reference/QUESTION_SYSTEM.md) -- reusable answers and question matching.
- [Changelog archive](./docs/changelog/) -- versioned release notes.
- [Validation archive](./docs/validation/) -- versioned verification records.
- [Windows build setup](./installer/README_BUILD_SETUP.txt) -- release packaging details.

---

## Contributing

Contributions are welcome. Useful areas include:

- Testing Windows, Chrome, locale, and Easy Apply variants without exposing real account data
- Improving UI clarity, onboarding, accessibility, and documentation
- Improving form-control reliability and diagnostic messages
- Adding translations and clearer examples
- Reviewing or improving Windows build and release workflows

Please keep pull requests focused, include the relevant tests or manual validation, and avoid unrelated refactors or generated build artifacts. Do not contribute CAPTCHA, 2FA, account-challenge, rate-limit, fingerprint, stealth, or access-control bypasses.

Read [CONTRIBUTING.md](./CONTRIBUTING.md) for local setup, pull-request guidance, privacy expectations, and product voice. Participation is governed by the [Code of Conduct](./CODE_OF_CONDUCT.md).

## Feedback and support

Thoughtful feedback helps make Autojobs clearer and safer for the next person.

| If you have... | The best next step |
| --- | --- |
| A reproducible problem | Open a [bug report](../../issues/new/choose) with sanitized steps, version, Windows/Chrome details, and relevant log lines. |
| A workflow idea | Open a [feature request](../../issues/new/choose) and describe the problem it would solve. |
| A question, tip, or general feedback | Start a [GitHub Discussion](../../discussions) when Discussions is enabled, or use the issue chooser. |
| A security concern | Follow [SECURITY.md](./SECURITY.md) and do not disclose it in a public issue. |

Before sharing anything, remove credentials, browser cookies, session data, resumes, contact details, private application information, and other personal data.

### Support the project

You do not need to write code to make a meaningful difference. You can:

- Star or watch the repository so useful updates are easier to find.
- Share a careful first-run experience or accessibility observation.
- Reproduce a bug and explain what you expected.
- Improve wording, examples, translations, or troubleshooting notes.
- Test a release or contribute a focused pull request.

For more ways to ask for help and share diagnostics safely, see [SUPPORT.md](./SUPPORT.md).

## License

Autojobs is available under the [Apache License 2.0](./LICENSE).

## Credits

Autojobs builds on the original work of [nicolomantini/LinkedIn-Easy-Apply-Bot](https://github.com/nicolomantini/LinkedIn-Easy-Apply-Bot), with a desktop-first workflow, local answer profiles, current Easy Apply compatibility work, and Windows packaging added on top.

---

<p align="center">
  <strong>Less repeated work. The same voice, choices, and next step.</strong>
</p>
