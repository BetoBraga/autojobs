# autojobs v2.7.1

## Windows build launcher hotfix

- Fixed a PowerShell parser error caused by `$LASTEXITCODE:` inside an interpolated string.
- `build_windows.bat` now creates `build.log` before PowerShell starts, so even parser/bootstrap errors are persisted.
- PowerShell transcript appends to the pre-created build log instead of deleting it.
- Parser/bootstrap stderr is appended to `build.log` after PowerShell exits.
- Portable release filename bumped to `autojobs-v2.7.1-portable-win64.zip`.
