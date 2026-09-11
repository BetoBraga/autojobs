#define MyAppName "Autojobs"
#define MyAppVersion "2.9.2"
#define MyAppPublisher "Autojobs"
#define MyAppExeName "autojobs.exe"

[Setup]
AppId={{8A6C1E14-8248-4BBF-B8D1-7A7DFF9B0E52}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Autojobs
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\installer-output
OutputBaseFilename=autojobs-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\favicon-autojobs.ico
WizardImageFile=..\assets\logo-autojobs.png
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\autojobs.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\themes.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\dist\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\prompt.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\answer-profile-template.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\BUILD_INFO.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\autojobs.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\autojobs.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\README.txt"; Description: "Open the beginner guide"; Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\autojobs.exe"; Description: "Launch Autojobs and continue the onboarding"; Flags: postinstall nowait skipifsilent

[Code]
var
  IntroPage, LoginPage, AnswersPage, SafetyPage, DailyUsePage: TWizardPage;

procedure AddBody(Page: TWizardPage; const Text: String);
var
  L: TNewStaticText;
begin
  L := TNewStaticText.Create(Page);
  L.Parent := Page.Surface;
  L.Left := 0;
  L.Top := 8;
  L.Width := Page.SurfaceWidth;
  L.Height := ScaleY(210);
  L.AutoSize := False;
  L.WordWrap := True;
  L.Caption := Text;
end;

procedure InitializeWizard;
begin
  IntroPage := CreateCustomPage(wpWelcome,
    'Welcome to Autojobs',
    'A quick onboarding before installation');
  AddBody(IntroPage,
    'Autojobs helps with repetitive LinkedIn Easy Apply steps. It keeps reusable answers locally, uses a dedicated Chrome profile, and gives you visible controls to start, stop, supervise, and recover a run. It does not bypass CAPTCHA or 2FA.');

  LoginPage := CreateCustomPage(IntroPage.ID,
    'LinkedIn login and browser modes',
    'Login is always visible');
  AddBody(LoginPage,
    'Use Open LinkedIn login inside Autojobs for the first sign-in. Password, 2FA, and challenges happen in a normal visible Chrome window. Headless mode only hides Chrome while Autojobs is searching and applying after a valid session already exists.');

  AnswersPage := CreateCustomPage(LoginPage.ID,
    'Answer Rules and AI-assisted JSON',
    'Configure once and reuse');
  AddBody(AnswersPage,
    'Answer Rules stores explicit answers and safe fallbacks. Export/import JSON to move them between machines. prompt.txt can be sent to ChatGPT together with your CV PDF to create a factual answer profile. Import the generated file, then review the imported answers inside Autojobs before running. Location fields use real autocomplete selections rather than raw text.');

  SafetyPage := CreateCustomPage(AnswersPage.ID,
    'Supervision and Failsafe Time',
    'The app should not loop silently');
  AddBody(SafetyPage,
    'Supervised mode asks whenever a visible Easy Apply answer is unresolved. Automatic mode uses your configured/default answers. Failsafe Time watches for a silent run. If activity stops, Autojobs flashes, saves a diagnostic report, and lets you recover, stop, or restart with visible Chrome in Supervised mode to identify the problem.');

  DailyUsePage := CreateCustomPage(SafetyPage.ID,
    'How you will use Autojobs',
    'Start, monitor, stop and customize');
  AddBody(DailyUsePage,
    'Search & Browser controls job titles, locations, filters, visible login and optional headless application runs. Answer Rules manages your reusable answers and JSON profiles. Run shows progress, current job, logs, Start and Stop. themes.json controls the visual themes and can be edited later without rebuilding Autojobs. After installation, the first-run onboarding explains these same controls again inside the app, and Setup & onboarding can reopen the guide anytime.');
end;
