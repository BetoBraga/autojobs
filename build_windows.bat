@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "BUILD_LOG=%~dp0build.log"
set "BOOTSTRAP_ERR=%~dp0build-bootstrap-error.log"

>"%BUILD_LOG%" echo autojobs Windows build
>>"%BUILD_LOG%" echo Build started: %DATE% %TIME%
>>"%BUILD_LOG%" echo Launcher: %~f0
>>"%BUILD_LOG%" echo.
if exist "%BOOTSTRAP_ERR%" del /q "%BOOTSTRAP_ERR%" >nul 2>&1

echo autojobs Windows build
echo A full log will be saved as build.log in this folder.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" 2>"%BOOTSTRAP_ERR%"
set "BUILD_EXIT=%ERRORLEVEL%"

if exist "%BOOTSTRAP_ERR%" (
  for %%A in ("%BOOTSTRAP_ERR%") do if %%~zA GTR 0 (
    >>"%BUILD_LOG%" echo.
    >>"%BUILD_LOG%" echo ===== PowerShell bootstrap/parser stderr =====
    type "%BOOTSTRAP_ERR%" >>"%BUILD_LOG%"
  )
  del /q "%BOOTSTRAP_ERR%" >nul 2>&1
)

if not "%BUILD_EXIT%"=="0" (
  echo.
  echo Build failed. Open build.log for the complete diagnostic output.
  echo Log: "%BUILD_LOG%"
  pause
  exit /b %BUILD_EXIT%
)

echo.
echo Build succeeded. You can share the CONTENTS of the dist folder as a portable app.
echo Python is not required on the destination computer. Google Chrome is required.
echo A ready ZIP is also created under the release folder.
echo Log: "%BUILD_LOG%"
echo.
pause
exit /b 0
