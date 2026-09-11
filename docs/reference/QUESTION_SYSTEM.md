# Easy Apply question system — v2.1

The question subsystem is designed around one fact: LinkedIn recruiters can create custom screening questions, so a finite hard-coded list can never be truly exhaustive.

## Resolution order

For every visible input the bot resolves an answer in this order:

1. Exact answer learned from a previous supervised run.
2. Conservative stable-fragment match against a learned answer.
3. Explicit answer configured in the optional question library.
4. Quick profile fields such as phone, salary and rate.
5. Existing LinkedIn/browser autofill value.
6. **Supervised mode:** pause and ask the user if the required field remains unresolved.
7. **Automatic mode:** use the configured default for numeric, text or boolean inputs.
8. For social/diversity choice fields, optionally choose `Prefer not to say` when that option is actually present.
9. If a required arbitrary choice cannot be mapped safely, skip that application and continue the run. The desktop app does not crash.

## Dublin / Ireland focus

The built-in library includes dedicated patterns for:

- legal right to work in Ireland;
- employment-permit / visa sponsorship;
- current Irish immigration permission and Stamp;
- Critical Skills / General Employment Permit;
- EU / EEA / Swiss citizenship;
- Dublin location, commute and relocation;
- hybrid days in a Dublin office;
- Garda vetting;
- Irish driving licence / vehicle access;
- English proficiency;
- notice period, earliest start date and salary expectations in EUR-oriented workflows.

No citizenship, immigration, demographic or social answer is inferred from another field.

## Social / diversity controls

The optional library contains explicit configuration points for gender, sex, transgender identity, ethnicity, race, disability, reasonable accommodation, veteran status, military service, sexual orientation, religion, civil/marital status, family/carer status, Traveller community, Roma identity, age band, date of birth and pronouns.

The default automatic policy is `Prefer not to say when available`. This only selects a non-disclosure option when the actual LinkedIn form contains such an option. Otherwise the normal typed default is considered. Users can override any category with an explicit stored answer.

## Run modes

### Supervised

When a required answer is missing, the bot pauses browser actions, brings the desktop application to the foreground, maximizes it, displays the question and its choices, and waits for the user. The answer is stored locally for future runs.

Closing the dialog or selecting **Skip this application** skips only that application; the run continues.

### Automatic

No question dialog is opened. Unknown inputs use:

- numeric default;
- text default;
- boolean default.

For arbitrary dropdown/radio options, a default is used only when it maps to a real option. The bot does not invent a random answer merely to get past validation.

## Failure isolation

- Every input is handled inside an exception boundary.
- Every job is handled inside an exception boundary.
- Browser session failures trigger a best-effort Chrome restart using the dedicated profile.
- UI queue events are isolated so a dialog/render problem does not stop Tk's main loop.
- Required unresolved questions skip the current application rather than terminating the process.
- CAPTCHA, 2FA and account challenges are never bypassed.

## Language-agnostic resolution (v2.6)

The engine must not require a translation table to keep moving. Before examining question wording it uses structural metadata exposed by the control: HTML `type`, `inputmode`, `autocomplete`, stable `name`/`data-*`/`componentkey` attributes, current autofill, option values and a persisted field signature. Unicode question normalization preserves non-Latin scripts.

Supervised answers are stored both by normalized visible question and, where available, by field signature. This allows reuse when LinkedIn later renders the same recruiter field in another locale.

Automatic mode resolves an unknown choice in this order: structural learned answer, learned question answer, catalog/profile, standard HTML semantics, existing autofill, typed defaults, then the configured autonomous choice fallback. `first_valid` picks the first concrete enabled option only as the final fallback and logs that assumption; `skip` preserves the conservative behavior.

Navigation similarly prefers stable selectors and the Easy Apply primary-action structure. Text labels are supplemental only.
