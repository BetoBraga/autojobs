from pathlib import Path

import pytest

from linkedin_easy_apply import browser


@pytest.mark.parametrize("headless", [False, True])
@pytest.mark.parametrize("explicit_driver", [False, True])
def test_chrome_keeps_background_pages_active(tmp_path, monkeypatch, headless, explicit_driver):
    from unittest.mock import Mock

    monkeypatch.delenv("CHROME_BIN", raising=False)
    monkeypatch.delenv("CHROMEDRIVER_PATH", raising=False)
    if explicit_driver:
        monkeypatch.setenv("CHROMEDRIVER_PATH", str(tmp_path / "chromedriver.exe"))
    driver = Mock()
    chrome = Mock(return_value=driver)
    monkeypatch.setattr(browser.webdriver, "Chrome", chrome)

    assert browser.build_chrome_driver(str(tmp_path / "profile"), headless=headless) is driver

    options = chrome.call_args.kwargs["options"]
    for flag in (
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-features=CalculateNativeWinOcclusion",
    ):
        assert flag in options.arguments
    assert ("--headless=new" in options.arguments) is headless
    assert ("service" in chrome.call_args.kwargs) is explicit_driver
    assert f"--user-data-dir={(tmp_path / 'profile').resolve()}" in options.arguments
    driver.execute_cdp_cmd.assert_called_once_with(
        "Emulation.setFocusEmulationEnabled", {"enabled": True}
    )
    driver.quit.assert_not_called()


def test_chrome_releases_profile_when_background_setup_fails(tmp_path, monkeypatch):
    from unittest.mock import Mock

    driver = Mock()
    driver.execute_cdp_cmd.side_effect = RuntimeError("CDP unavailable")
    monkeypatch.setattr(browser.webdriver, "Chrome", Mock(return_value=driver))

    with pytest.raises(RuntimeError, match="CDP unavailable"):
        browser.build_chrome_driver(str(tmp_path / "profile"), headless=True)

    driver.quit.assert_called_once_with()


def test_desktop_ui_contains_requested_modes_defaults_ai_and_portability():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert '"Guided (recommended)": "supervised"' in source
    assert '"Automatic": "automatic"' in source
    assert "default_numeric_var" in source
    assert "default_text_var" in source
    assert "default_boolean_var" in source
    assert "Coming soon" in source
    assert "by borerto" in source
    assert "Dublin essentials" in source
    assert "Import AI answers…" in source
    assert "Export answer template…" in source
    assert "Search without showing Chrome" in source
    assert "Your answer" in source


def test_supervised_prompt_maximizes_desktop_app():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'self.state("zoomed")' in source
    assert "_maximize_for_question" in source


def test_headless_is_wired_from_config_to_driver():
    root = Path(__file__).resolve().parents[1]
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    browser = (root / "linkedin_easy_apply" / "browser.py").read_text(encoding="utf-8")
    assert "headless=self.config.headless_browser" in bot
    assert 'options.add_argument("--headless=new")' in browser
    assert 'options.add_argument("--window-size=1920,1080")' in browser

def test_login_setup_always_uses_visible_browser():
    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")
    bot = (root / "linkedin_easy_apply" / "bot.py").read_text(encoding="utf-8")
    assert "build_chrome_driver(self.config_data.chrome_profile_dir, headless=False)" in app
    assert "wait_for_manual_login=not self.config.headless_browser" in bot
    assert "Headless Chrome is not signed in. Use 'Open LinkedIn login' once with a visible browser" in bot



def test_autojobs_brand_themes_and_credits_are_present():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app.py").read_text(encoding="utf-8")
    assert 'APP_TITLE = "Autojobs"' in source
    assert "Theme" in source
    assert "Reload" in source
    assert "themes_file_path" in source
    assert 'text="credits"' in source
    assert "impacted by layoffs" in source
    assert "I'm praying for you" in source
    assert "nicolomantini's project" in source
    assert "https://borerto.com" in source
    assert "logo-autojobs.png" in source
    assert "favicon-autojobs.ico" in source
    assert "Setup & onboarding" in source
    assert "Waiting reminder" in source
    assert "FailsafeDialog" in source


def test_disclaimer_help_responsive_and_ai_import_guidance_are_present():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "First time? Choose your jobs" in source
    assert 'text="?"' in source
    assert "_apply_responsive_layout" in source
    assert "import_me_on_autojobs.json" in source
    assert "NO JSON KNOWLEDGE NEEDED" in source
    assert "Open log file" in source
    assert "changed with a little extra care for special people" in source
    assert 'text="by roberto"' in source


def test_disclaimer_can_be_hidden_and_ai_files_folder_is_discoverable():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "Don't show this again" in source
    assert "_hide_run_disclaimer" in source
    assert "How do I prepare my answers?" in source
    assert "_open_portable_files_folder" in source


def test_search_scope_is_not_hardcoded_to_dublin_and_maximum_coverage_preserves_remote_intent():
    root = Path(__file__).resolve().parents[1]
    app = (root / "app.py").read_text(encoding="utf-8")
    config = (root / "linkedin_easy_apply" / "config.py").read_text(encoding="utf-8")
    assert 'locations: list[str] = field(default_factory=lambda: ["Worldwide"])' in config
    assert 'self.locations = ["Worldwide"]' in config
    assert "One location per line: a city, country, or Worldwide. For remote jobs, select Remote below." in app
    assert "Remote-only or country-specific campaigns stay Remote-only/country-specific" in app
    assert "for var in self.work_vars.values():\n            var.set(False)" not in app
