# Answer Profile JSON format

Answer Profile JSON is the portable backup/share format for answer rules.

## Privacy boundary

Included:

- numeric/text/boolean fallbacks;
- social-question strategy;
- explicitly configured question-catalog answers;
- learned exact recruiter-question answers.

Excluded:

- job-search targets and filters;
- resume and cover-letter paths;
- Chrome profile/session data;
- application history/CSV;
- LinkedIn credentials (the app never stores the password).

The JSON **can still contain sensitive information** when you explicitly configured social/diversity answers. Treat it like personal data.

## Schema

```json
{
  "schema": "linkedin-easy-apply-answer-profile",
  "version": 2,
  "exported_at": "2026-09-09T18:00:00+00:00",
  "defaults": {
    "numeric": "0",
    "text": "N/A",
    "boolean": "No",
    "social_question_strategy": "prefer_not_to_say"
  },
  "profile_answers": {
    "ie_work_authorized": "",
    "ie_sponsorship": "",
    "...": ""
  },
  "questions": [
    {
      "key": "ie_work_authorized",
      "question": "Legally authorised to work in Ireland",
      "category": "Ireland & work eligibility",
      "type": "boolean",
      "choices": ["Yes", "No"],
      "dublin_recommended": true,
      "social": false,
      "answer": ""
    }
  ],
  "learned_answers": {}
}
```

## Import behavior

### Merge

- keeps current answers;
- imports new answers;
- imported values win on matching keys/questions;
- imported fallback settings replace current fallback settings when present.

### Replace

- clears existing `profile_answers` and `learned_answers` first;
- imports the JSON values;
- imported fallback settings replace current fallback settings when present.

Search settings, browser settings and application history are never changed by either mode.

## Compatibility

The importer also accepts a full application `config.json` and extracts only its answer-related fields. Unknown future schema versions are rejected with a readable error instead of partially importing them.


## Complete question template

Version 2 exports every built-in catalog question, including questions that have never been answered.
Blank answers are represented by the empty string `""`. The `questions` array is the human-readable view, while `profile_answers` contains the same catalog as simple key/value pairs.

You can export the JSON, fill only the blanks you care about, and import it again. Empty values are ignored during Merge and remain empty during Replace; they do not create fake answers.

Version 1 files remain import-compatible.
