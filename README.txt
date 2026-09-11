autojobs v2.9 — QUICK START FOR NON-TECHNICAL USERS
=====================================================

WHAT AUTOJOBS DOES
------------------
autojobs helps with repetitive LinkedIn Easy Apply steps using the job filters and answers you choose. It gives you a desktop interface to sign in, configure answers, start/stop the run, watch progress, and recover if something gets stuck.

IMPORTANT
---------
LinkedIn may restrict accounts that use third-party automation. autojobs does not bypass CAPTCHA, 2FA, account challenges, or other access controls. Use it only if you understand and accept that account risk.

BEST WAY TO INSTALL: AUTOJOBS SETUP
-----------------------------------
If you received autojobs-Setup.exe:

1. Double-click autojobs-Setup.exe.
2. Read the short onboarding pages in the installer.
3. Keep the default install folder unless you have a reason to change it.
4. Choose whether you want a Desktop shortcut.
5. Finish installation.
6. autojobs opens and shows its first-run Setup & Onboarding guide.

The installer is per-user, so it normally does not need administrator access. It installs autojobs.exe plus the editable support files themes.json, README.txt, prompt.txt, and answer-profile-template.json.

PORTABLE VERSION
----------------
If you received a ZIP instead of autojobs-Setup.exe:

1. Extract the entire ZIP to a normal folder.
2. Do not run autojobs.exe from inside a ZIP preview.
3. Keep these files together:
   - autojobs.exe
   - themes.json
   - README.txt
   - prompt.txt
   - answer-profile-template.json
4. Double-click autojobs.exe.

You can move the whole folder later. autojobs finds themes.json relative to autojobs.exe, so moving it does not break the theme path.

FIRST-RUN ONBOARDING
--------------------
The first time autojobs opens, it shows a Setup & Onboarding wizard explaining:

- LinkedIn login;
- visible vs headless browser;
- job titles and locations;
- Answer Rules and JSON profiles;
- Supervised vs Automatic mode;
- Failsafe Time;
- starting, monitoring, and stopping a run.

You can reopen it any time with the "Setup & onboarding" button at the top of autojobs.

FIRST-TIME SETUP
----------------
The steps below complete the first-time LinkedIn setup.

FIRST-TIME LINKEDIN SETUP
-------------------------
1. Open "1. Search & Browser".
2. Click "Open LinkedIn login".
3. Chrome ALWAYS opens visibly for login.
4. Sign in normally.
5. Complete password, 2FA, CAPTCHA, or security challenges yourself.
6. When autojobs detects the logged-in session, it saves the Chrome profile for future runs.
7. Choose your Resume/CV.
8. Add job titles, one per line.
9. Check the search locations. The fresh-install default is Worldwide. Replace it with a city, country, region, Remote, or multiple lines such as Portugal and Brazil.
10. Choose filters such as date posted, experience level, and work model.
11. Choose Supervised or Automatic mode.
12. Save.

HEADLESS / BACKGROUND MODE
--------------------------
"Run Chrome in background (headless)" means:

- Login: ALWAYS visible.
- 2FA/security checks: ALWAYS handled by you in visible Chrome.
- Searching and applying after login: Chrome can be hidden.
- Supervised unknown question: the autojobs desktop application appears; the browser can remain hidden.

You do not need to keep the mouse over Chrome or keep its window in the foreground. Visible Chrome can also be minimized while the automation runs. Keep the computer awake and connected to the internet; background mode cannot run while Windows is asleep or hibernating. Supervised questions and submission confirmations still need your response.

If LinkedIn logs you out, autojobs does not try to perform an invisible login. Click "Open LinkedIn login" again and refresh the session visibly.

LOCATION FIELDS AND DROPDOWNS
-----------------------------
LinkedIn often shows location as a text-looking field that is actually an autocomplete/select control.

autojobs does not treat these fields as normal text. It:

1. detects ARIA combobox/typeahead/autocomplete controls;
2. types the configured location;
3. waits for LinkedIn's suggestion list;
4. selects the closest real suggestion;
5. commits that selection before continuing.

This is important because a location can look filled on screen but still be invalid until one of LinkedIn's suggestions is selected.


LOCATION SAFETY CHECK
----------------------------
LinkedIn can occasionally leak jobs outside the typed search location, especially broad remote/Europe-wide results. LinkedIn search remains the primary filter; autojobs also checks the opened job when reliable location metadata is available.
The Search & Browser tab has an optional post-open location-conflict checkbox. It is OFF by default. Location is used to scope the LinkedIn search, but returned jobs are not rejected again based on page metadata unless you explicitly enable this extra guard. Maximize coverage always disables the post-open guard. It does not change your search locations and does not clear your Remote/Hybrid/On-site selection.

Example with the DEFAULT setting:
- configured search: Dublin, County Dublin, Ireland
- result returned by LinkedIn: Lisbon, Portugal
- action: continue to Easy Apply; location does not block it

Example only if you explicitly enable the optional post-open conflict guard:
- configured search: Dublin, County Dublin, Ireland
- verified high-confidence result: Lisbon, Portugal
- action: filtered before Easy Apply and recorded in applications.csv

By default autojobs continues every job LinkedIn returns for each configured search scope, including broader/remote/missing/inconsistent post-open location metadata. This prevents location metadata from becoming an application blocker. If you explicitly enable the optional post-open guard, only high-confidence verified conflicts can be rejected.

SETTING UP ANSWERS
------------------
Open "2. Answer Rules".

You can:
- search the full question library;
- select a question and save an explicit reusable answer;
- set fallback answers for unknown number, text, and Yes/No questions;
- configure social/diversity questions only if you want to disclose them;
- export your answer profile to JSON;
- import an answer profile JSON.

The exported JSON includes every built-in question, including blank/unanswered questions.

USING CHATGPT + YOUR CV TO PREPARE ANSWERS
------------------------------------------
The file prompt.txt is designed to be sent to ChatGPT together with your Resume/CV PDF.

1. Open ChatGPT.
2. Upload prompt.txt.
3. Upload your Resume/CV PDF.
4. Ask ChatGPT to follow prompt.txt.
5. ChatGPT should create a ready file named exactly:
   import_me_on_autojobs.json
6. Download that file from ChatGPT. You do NOT need to open or edit it manually.
7. In autojobs, open "2. Answer Rules" and click "Import AI answers...". Hover that button if you need the visual step-by-step again.
8. Select import_me_on_autojobs.json.
9. Use Merge to keep current answers or Replace to replace explicit/learned answers.
10. Review important answers before running.

The AI prompt asks ChatGPT to fill as much as can be truthfully derived from factual CV content. It may safely calculate or normalize non-sensitive facts when the evidence is clear. Examples include experience duration from dates and a complete normalized contact location.

Example:
- CV says: Dublin, Ireland
- AI may fill: Dublin, County Dublin, Ireland

Another example:
- CV says: Santos, SP, Brazil
- AI may fill: Santos, São Paulo, Brazil

AI should NOT infer your current residence only because a past employer or university was in a city. It should also never infer work authorization, citizenship/visa status, or social/sensitive attributes from location, name, language, school, or other indirect signals.

SUPERVISED MODE
---------------
Recommended for first runs.

When autojobs finds a visible Easy Apply question that has no safe answer:

1. browser processing pauses;
2. autojobs comes to the front and maximizes;
3. you enter/select the answer;
4. autojobs saves it locally;
5. future similar applications reuse it.

AUTOMATIC MODE
--------------
Automatic mode does not ask for unknown questions. It uses:

1. learned answers;
2. configured question answers;
3. known profile fields;
4. HTML/control semantics;
5. typed default answers;
6. when enabled, the configured first-valid-option fallback for a completely unknown required choice.

Native selects, radio buttons and checkboxes are verified after the click/change events. A placeholder such as "Select an option" never counts as a real answer. Yes/No controls are identified from their actual options/values before question wording, so words such as "Update" cannot be mistaken for a date field.

In Supervised mode, an unresolved choice is shown to you and the answer is saved as a Learned Answer for reuse.

FAILSAFE TIME: PREVENTING SILENT LOOPS
--------------------------------------
Failsafe Time is in "1. Search & Browser" under run behavior.

Default: 60 seconds.
Allowed range: 15 to 900 seconds.

Failsafe Time means: if the active run produces no log, status, or progress event for that period, autojobs assumes something may be stuck.

When failsafe triggers:

- the app flashes/beeps like a notification;
- a popup appears;
- a diagnostic report is saved locally;
- autojobs shows the current job/status plus recent logs in that report.

You can choose:

1. Restart visible + Supervised
   Recommended. Stops the stalled browser and restarts with a visible browser in Supervised mode so you can see the failing page/field and answer manually.

2. Try browser recovery
   Forces the current WebDriver/browser connection to reset so the bot can attempt its normal recovery path.

3. Keep waiting
   Resets the failsafe timer and continues waiting.

4. Stop run
   Stops the automation safely.

Failsafe is paused while autojobs is intentionally waiting for your answer or your Submit confirmation, so it should not warn just because you are reading a popup.

Diagnostic reports are stored in the autojobs application-data folder under:

failsafe-reports

STARTING A RUN
--------------
1. Make sure LinkedIn login was completed with "Open LinkedIn login".
2. Open "3. Run".
3. Press "Start supervised run" or "Start automatic run".
4. Watch Current Job, counters, status, progress, and logs.

STOPPING A RUN
--------------
Click "Stop" in the Run tab.

autojobs asks the worker to stop as safely as possible after the current browser operation. If you close the app while a run is active, autojobs asks before exiting.

RESULTS
-------
Application results are written to applications.csv in the autojobs application-data folder.

CHANGING THE THEME
------------------
Use the Theme menu at the top of autojobs.

Default themes:
- Ocean
- Emerald
- Sunset
- Midnight
- Lavender

Themes live in themes.json next to autojobs.exe. You can add, edit, rename, or remove themes after build/install. Click Reload in autojobs after editing themes.json.

If themes.json has a mistake, autojobs falls back to built-in safe themes instead of crashing.

ANSWER JSON BACKUP
------------------
Use Export answer template to create an answer-profile backup/template.

The JSON contains:
- all catalog questions, including blank answers;
- explicit configured answers;
- learned recruiter answers;
- fallback settings.

It does NOT include:
- Chrome login/session;
- Resume/CV file contents;
- application history;
- search settings.

Because your JSON may contain personal answers, store it somewhere appropriate.


PERSISTENT DEBUG LOG
--------------------
autojobs writes a persistent file named autojobs.log in the autojobs application-data folder. Use "Open log file" in 3. Run or the ? Help button to open it.

The log has a hard 100 MB limit. When the next record would exceed 100 MB, autojobs deletes/truncates the old log and starts a fresh one automatically. This keeps recent diagnostic detail without using unlimited disk space.

When reporting a problem, include the relevant applications.csv rows and autojobs.log.

TROUBLESHOOTING
---------------
LinkedIn location is visible but says invalid:
- v2.5 should select a real suggestion automatically;
- use Supervised mode if LinkedIn shows a new location widget variant;
- Failsafe can restart visibly and save a report if the page gets stuck.

LinkedIn asks you to sign in during a headless run:
- stop the run;
- click Open LinkedIn login;
- sign in visibly again;
- restart the run.

An unknown or changed question appears:
- use Supervised mode;
- autojobs asks for any unresolved visible Easy Apply question, even if LinkedIn did not expose an HTML required marker;
- answer it once;
- autojobs stores it as a Learned Answer for future use;
- if a previously saved dropdown answer no longer exists, Supervised shows the current choices once instead of silently failing.

The run looks frozen:
- wait for the Failsafe Time popup;
- choose Restart visible + Supervised to inspect the failure;
- check the generated failsafe report.

Theme looks wrong:
- click Reload;
- verify themes.json;
- if invalid, autojobs uses fallback themes.

TO TURN AUTOJOBS ON
-------------------
Installed version:
- Start Menu > autojobs, or double-click the Desktop shortcut if you created one.

Portable version:
- double-click autojobs.exe.

TO TURN AUTOJOBS OFF
--------------------
1. Stop any active run.
2. Close the autojobs window.

UNINSTALLING
------------
If installed with autojobs-Setup.exe:
- Windows Settings > Apps > Installed apps > autojobs > Uninstall.

The dedicated local autojobs data/profile folder may remain so an upgrade does not lose your settings. You can remove that folder manually later if you intentionally want to erase local autojobs settings and the saved Chrome profile.

LANGUAGES AND AUTONOMOUS FORM HANDLING
--------------------------------------
autojobs does not need a separate language pack for each LinkedIn locale. It first reads the field itself: input type, input mode, HTML autocomplete meaning, stable field name/signature, available choices and existing LinkedIn autofill. Learned answers are also tied to a structural signature when possible.

In Automatic mode, if a dropdown/radio question is completely new and none of those signals can map a truthful configured answer, the default setting is to choose the first concrete valid option so the application can keep moving. This last-resort assumption is written to autojobs.log. You can disable it in 2. Answer Rules if you would rather skip ambiguous applications.

For best accuracy, still configure Answer Rules and do an initial Supervised run. The language-agnostic fallback is for resilience, not a guarantee that the meaning of an arbitrary recruiter-written question can always be inferred from HTML alone.


PORTABLE WINDOWS BUILD
----------------------
The destination computer does not need Python. Build autojobs once on a Windows build computer, then copy/zip the contents of dist. Keep autojobs.exe, themes.json, README.txt, prompt.txt and answer-profile-template.json together. Google Chrome is required, and first-time driver resolution may require internet access.


MAXIMIZE COVERAGE (v2.9)
------------------------
The Search & Browser tab includes a Maximize coverage button. It sets Maximum successful applications to 0 (unlimited), Result pages per search to 0 (until exhausted), Date posted to Any time, clears experience filters, switches to Automatic, disables manual submit review, enables the deterministic last-resort choice fallback, disables post-open location rejection, and keeps action delays at about 3-7 seconds or slower. It preserves your positions, search locations, work-type filters and blacklists. Remote-only searches stay remote-only; country/city searches stay exactly as configured.

The Run tab separates Filtered from Skipped. Filtered means autojobs intentionally did not open/continue Easy Apply (for example verified location conflict, already applied, blacklist, or no Easy Apply). Skipped now means an Easy Apply attempt started but could not be completed or was deliberately declined. The Easy Apply completion rate is Applied / Attempted.

100% of all LinkedIn search results is not technically possible because some jobs are not Easy Apply, some are duplicates/already applied, and some may require truthful work-authorisation/visa information that autojobs will not invent. For the highest unattended completion rate, configure those factual eligibility answers in Answer Rules once, test them in Supervised mode, then use Automatic.


LOW DELAY / THROTTLING WARNING
------------------------------
LinkedIn does not publish a guaranteed safe automation delay. Very small action delays can increase the chance of throttling, challenge prompts, or temporary restrictions sometimes described as a soft ban. autojobs shows an inline warning and asks for confirmation before a run when the configured delay is aggressive. For long unattended runs, roughly 3-7 seconds or slower is used as a conservative baseline, not a guarantee.


## Remote / worldwide searches

Search locations are not hard-coded to Dublin. Use one scope per line: `Dublin, County Dublin, Ireland`, `Portugal`, `Brazil`, `European Union`, `Remote`, or `Worldwide`. For remote-only campaigns, set the location scope to `Remote` or `Worldwide` and select the Remote work-type filter. In Automatic coverage mode, post-open location metadata does not block an application unless you explicitly enable the optional post-open conflict guard.
