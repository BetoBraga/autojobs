AUTOJOBS SETUP BUILDER
======================

The Windows installer is generated with Inno Setup 6 after autojobs.exe is built.

Normal users should use autojobs-Setup.exe from the release/artifact. They do not
need Python or Inno Setup.

Developer build:
1. Install Python 3.13 and Inno Setup 6.
2. Run build_windows.bat.
3. The portable files are created in dist\.
4. If Inno Setup is installed, the installer is created as:
   installer-output\autojobs-Setup.exe

The installer includes onboarding pages and then launches the in-app onboarding
on first run.
