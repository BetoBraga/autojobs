# autojobs v2.7.0

- Location safety guard is now fail-open for missing/ambiguous LinkedIn metadata and rejects only verified conflicts.
- Expanded best-effort location extraction for current LinkedIn top-card variants.
- Preserved language-agnostic Automatic fallbacks and Supervised learned-answer behavior from v2.6.
- Added persistent build.log and checked native process exit codes in the Windows builder.
- Windows build now creates a clean portable dist folder plus release/autojobs-v2.7.0-portable-win64.zip.
- Added BUILD_INFO.txt explaining that destination computers do not need Python.
- Added five playful themes: Ctrl+Alt+Hired, Recruiter Ghosted Me, Coffee Before Interviews, Terminal Goblin and Merge Conflict.
- Added “Don’t show this again” to the pre-run disclaimer.
- Added “Where are these files?” beside Import AI answers.
