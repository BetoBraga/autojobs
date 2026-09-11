# autojobs v2.3.0

- Renamed desktop application and Windows executable to `autojobs`.
- Added external, portable `themes.json` resolved relative to `autojobs.exe`.
- Added five default themes: Ocean, Emerald, Sunset, Midnight, Lavender.
- Added dynamic Theme selector and Reload control; themes may be added/edited/removed without rebuilding.
- Added safe built-in fallback if `themes.json` is missing/invalid/unwritable.
- Added non-technical `README.txt` covering install, setup, start, stop, headless mode, answer profiles and themes.
- Added self-contained `prompt.txt` for generating an autojobs JSON answer profile from an uploaded resume/CV while preventing unsupported/sensitive inference and limiting free-text answers to 230 characters.
- Added subtle footer `credits` easter egg with a dedication to people affected by layoffs/job loss.
- New installs use `%APPDATA%\\autojobs` (or platform equivalent), with one-time compatibility loading from the previous app config location.
- Windows build/GitHub Actions now package the editable helper files beside `autojobs.exe`.
