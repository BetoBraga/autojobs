import ast
from pathlib import Path


def test_python_sources_parse():
    root = Path(__file__).resolve().parents[1]
    for path in [root / "app.py", root / "easyapplybot.py", *sorted((root / "linkedin_easy_apply").glob("*.py"))]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_autocomplete_wiring_requires_real_matching_suggestion_and_has_location_retries():
    root = Path(__file__).resolve().parents[1]
    browser = (root / "linkedin_easy_apply" / "browser.py").read_text(encoding="utf-8")
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    assert "fill_autocomplete(" in bot
    assert "queries = [value]" in browser
    assert 'queries.append(f"{parts[0]}, {parts[-1]}")' in browser
    assert "best_score >= 50.0" in browser
    assert "or len(options) == 1" not in browser


def test_failsafe_is_bounded_and_can_restart_visible_supervised():
    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")
    config = (root / "linkedin_easy_apply" / "config.py").read_text(encoding="utf-8")
    assert "failsafe_seconds: int = 60" in config
    assert "restart_supervised" in app
    assert "self.headless_var.set(False)" in app
    assert 'self.config_data.run_mode = "supervised"' in app
    assert "failsafe-reports" in app


def test_credits_message_contains_no_grammatical_dash():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app.py").read_text(encoding="utf-8")
    start = source.index("class CreditsDialog")
    end = source.index("class AIBalloon", start)
    credits = source[start:end]
    assert "—" not in credits
    assert "–" not in credits
    assert "changed with a little extra care for special people" in credits
    assert "alterada com" not in credits
    assert "https://borerto.com" in credits


def test_form_scanner_is_scoped_to_easy_apply_and_actions_are_localized():
    root = Path(__file__).resolve().parents[1]
    browser = (root / "linkedin_easy_apply" / "browser.py").read_text(encoding="utf-8")
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    assert "applicationContainers" in browser
    assert "for (const container of applicationContainers) collect(container)" in browser
    assert "candidatura" in bot.lower()
    assert "application stalled on the same step" in bot
    assert "verified location conflict" in bot
    assert "extract_job_location" in bot


def test_supervised_prompts_even_without_html_required_marker():
    root = Path(__file__).resolve().parents[1]
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    assert "if resolution.should_prompt and not current" in bot
    assert "if resolution.should_prompt:" in bot
    assert "and required and not current" not in bot


def test_persistent_log_and_custom_answer_dialog_are_wired():
    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")
    logging_utils = (root / "linkedin_easy_apply" / "logging_utils.py").read_text(encoding="utf-8")
    assert "CappedFileHandler" in app
    assert "MAX_LOG_BYTES = 100 * 1024 * 1024" in logging_utils
    assert "CustomAnswerDialog" in app
    assert ".remember_answer(" in app
    assert "HelpCenterDialog" in app
    assert "HighlightOverlay" in app


def test_field_writes_are_verified_and_validation_rechecks_become_effectively_required():
    root = Path(__file__).resolve().parents[1]
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    assert "effective_required = required or force_required" in bot
    assert "did not retain/validate requested value" in bot
    assert "element.get_attribute(\"value\")" in bot
    assert "Could not select a valid option for:" in bot
    assert "Could not select a valid choice for:" in bot


def test_results_reasons_include_the_specific_unresolved_field_when_available():
    root = Path(__file__).resolve().parents[1]
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    assert 'self._last_form_issue = ""' in bot
    assert 'detail = f": {self._last_form_issue}" if self._last_form_issue else ""' in bot
    assert 'f"skipped: required question was not answered after live-DOM retries{detail}"' in bot


def test_language_agnostic_form_metadata_and_structural_actions_are_present():
    root = Path(__file__).resolve().parents[1]
    browser = (root / "linkedin_easy_apply" / "browser.py").read_text(encoding="utf-8")
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    config = (root / "linkedin_easy_apply" / "config.py").read_text(encoding="utf-8")
    assert "fieldSignature" in browser
    assert "inputMode" in browser
    assert "autocomplete:" in browser
    assert "componentKey" in browser
    assert "button.artdeco-button--primary" in browser
    assert "button.artdeco-button--primary" in bot
    assert "submission confirmed structurally" in bot
    assert "automatic_choice_strategy" in config
    assert "answer_signatures" in config


def test_v28_build_is_logged_checked_and_portable():
    root = Path(__file__).resolve().parents[1]
    ps1 = (root / "build_windows.ps1").read_text(encoding="utf-8")
    bat = (root / "build_windows.bat").read_text(encoding="utf-8")
    assert "Start-Transcript" in ps1
    assert "Invoke-Checked" in ps1
    assert "autojobs-v2.9.2-portable-win64.zip" in ps1
    assert "Python is NOT required" in ps1
    assert "build.log" in bat


def test_location_is_search_scope_by_default_and_post_open_filter_is_opt_in():
    root = Path(__file__).resolve().parents[1]
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    config = (root / "linkedin_easy_apply" / "config.py").read_text(encoding="utf-8")
    app = (root / "app.py").read_text(encoding="utf-8")
    assert "post_open_location_filter: bool = False" in config
    assert "self.config.post_open_location_filter" in bot
    assert "self.config.strict_location_filter and requested_location" not in bot
    assert "Post-open location filtering is disabled; location only scopes the LinkedIn search" in bot
    assert "self.post_open_location_var.set(False)" in app
    assert "job location could not be verified for strict search" not in bot


def test_pyinstaller_excludes_build_only_pytest_modules():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "autojobs.spec").read_text(encoding="utf-8")
    assert "excludes=['pytest', '_pytest']" in spec


def test_easy_apply_control_scanner_covers_native_and_aria_control_families():
    root = Path(__file__).resolve().parents[1]
    browser = (root / "linkedin_easy_apply" / "browser.py").read_text(encoding="utf-8")
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    for token in (
        "select-one", "select-multiple", "aria-radio", "aria-checkbox",
        "aria-combobox", "aria-spinbutton", "aria-switch", "contenteditable",
    ):
        assert token in browser or token in bot
    assert "_read_native_select" in bot
    assert "_select_option" in bot
    assert "_activate_choice" in bot
    assert "Keys.SPACE" in bot
    assert "_verify_required_controls" in bot
    assert "_aria_combobox_commit_verified" in bot
    assert "placeholder" in bot.lower()


def test_aggressive_delay_warning_is_wired_to_ui_and_runtime():
    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    config = (root / "linkedin_easy_apply" / "config.py").read_text(encoding="utf-8")
    assert "delay_is_aggressive" in config
    assert "Very low action delay" in app
    assert "_confirm_aggressive_delay" in app
    assert "throttle" in bot
    assert "RECOMMENDED_MIN_DELAY_SECONDS = 3.0" in config
    assert "RECOMMENDED_MAX_DELAY_SECONDS = 7.0" in config
