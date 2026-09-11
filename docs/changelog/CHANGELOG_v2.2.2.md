# v2.2.2 — Complete JSON question template

- Answer Profile schema bumped to v2.
- `Export JSON…` now includes every built-in question, including unanswered questions.
- Empty catalog answers are represented explicitly as `""` instead of being omitted.
- Added human-readable `questions` array with key, question label, category, input type, choices, Dublin/social flags and answer.
- `profile_answers` remains available as a simple complete key/value map for easy external editing.
- Import supports both legacy v1 JSON files and the new complete v2 format.
- Blank imported values do not create fake configured answers.
- Added `answer-profile-template.json` as a ready-to-edit complete template.
- Regression suite expanded to cover complete blank-question export and v2 re-import.
