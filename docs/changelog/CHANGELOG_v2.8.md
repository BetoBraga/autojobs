# autojobs v2.8.0

## Easy Apply form-controls reliability

- Fixed native LinkedIn `<select>` controls so a placeholder such as `Select an option` is never treated as an existing answer.
- Fixed boolean inference: Yes/No option structure and stable raw values (`true/false`, `1/0`) now outrank question wording. This prevents `Update` from being misclassified as a date because it contains `date` as a substring.
- Native selects now use three verified commit routes: Selenium Select, concrete option click, and the native HTMLSelectElement value setter with `input/change/blur` events.
- Hidden native radio/checkbox inputs are operated through their visible labels first, then verified through `checked`/`aria-checked` state.
- Added coverage for native radio, checkbox, single/multi select, input/textarea, role combobox/radio/checkbox/switch/spinbutton, contenteditable controls and scoped file upload.
- Custom ARIA combobox selections are now verified from `aria-selected`, `aria-activedescendant`, committed value/text and validity instead of treating a successful click as sufficient.
- Required controls are re-inspected from the live Easy Apply DOM after React/SDUI handles events; the run will not advance while a required placeholder/invalid control remains.
- File uploads are now scoped to the active Easy Apply form rather than every file input on the LinkedIn page.
- Added end-to-end regression coverage for the observed `Edge Device Update Management` Yes/No select and hidden native radio behavior.

## Build

- Version bumped to 2.8.0 across the package, installer, Windows build and GitHub Actions portable artifact.
- The v2.7.1 build-log parser hotfix remains intact.
