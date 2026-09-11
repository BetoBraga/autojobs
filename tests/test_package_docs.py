from pathlib import Path


def test_nontechnical_readme_covers_start_stop_setup_headless_and_themes():
    root = Path(__file__).resolve().parents[1]
    text = (root / "README.txt").read_text(encoding="utf-8")
    for phrase in (
        "FIRST-TIME SETUP",
        "TO TURN AUTOJOBS ON",
        "TO TURN AUTOJOBS OFF",
        "HEADLESS / BACKGROUND MODE",
        "CHANGING THE THEME",
        "Open LinkedIn login",
        "AUTOJOBS SETUP",
        "FAILSAFE TIME",
        "LOCATION FIELDS AND DROPDOWNS",
    ):
        assert phrase in text


def test_prompt_is_self_contained_and_conservative():
    root = Path(__file__).resolve().parents[1]
    text = (root / "prompt.txt").read_text(encoding="utf-8")
    from linkedin_easy_apply.question_catalog import QUESTION_CATALOG

    assert "import_me_on_autojobs.json" in text
    assert "create and attach/download a real file" in text
    assert "230 characters or fewer" in text
    assert "Never invent" in text
    assert "LOCATION IS IMPORTANT" in text
    assert "conservative logical or mathematical deductions" in text
    assert "do not infer" in text.lower()
    assert "ALL catalog keys" in text
    for q in QUESTION_CATALOG:
        assert f"{q.key} |" in text


def test_windows_build_packages_portable_external_files():
    root = Path(__file__).resolve().parents[1]
    ps = (root / "build_windows.ps1").read_text(encoding="utf-8")
    spec = (root / "autojobs.spec").read_text(encoding="utf-8")
    assert "autojobs.exe" in ps
    for filename in ("themes.json", "README.txt", "prompt.txt", "answer-profile-template.json"):
        assert filename in ps
    assert "name='autojobs'" in spec
    assert "logo-autojobs.png" in spec
    assert "favicon-autojobs.ico" in spec
    assert "icon='assets/favicon-autojobs.ico'" in spec
    installer = (root / "installer" / "autojobs.iss").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
    assert "autojobs-Setup" in installer
    assert '#define MyAppName "Autojobs"' in installer
    assert "SetupIconFile=..\\assets\\favicon-autojobs.ico" in installer
    assert "WizardImageFile=..\\assets\\logo-autojobs.png" in installer
    assert "Failsafe Time" in installer
    assert "Build Windows Setup" in workflow
