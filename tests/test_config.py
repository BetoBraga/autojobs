from pathlib import Path

from linkedin_easy_apply.config import (
    AppConfig, normalize_question, delay_is_aggressive, delay_warning_text,
    RECOMMENDED_MIN_DELAY_SECONDS, RECOMMENDED_MAX_DELAY_SECONDS,
)


def test_normalize_question():
    assert normalize_question("  How many\nYears   of experience? ") == "how many years of experience"


def test_config_normalizes_lists_and_ranges(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config = AppConfig(
        positions=[" Engineer ", "Engineer", ""],
        locations=["Remote"],
        experience_levels=[2, 2, 9],
        work_types=[2, 3, 9],
        min_delay_seconds=4,
        max_delay_seconds=2,
    ).normalized()
    assert config.positions == ["Engineer"]
    assert config.experience_levels == [2]
    assert config.work_types == [2, 3]
    assert config.max_delay_seconds == 4
    assert config.output_csv.endswith("applications.csv")


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "settings.json"
    original = AppConfig(positions=["Data Engineer"], locations=["São Paulo"], answers={"Question?": "Yes"})
    original.save(path)
    loaded = AppConfig.load(path)
    assert loaded.positions == ["Data Engineer"]
    assert loaded.locations == ["São Paulo"]
    assert loaded.answers["question"] == "Yes"


def test_headless_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "settings.json"
    AppConfig(headless_browser=True).save(path)
    assert AppConfig.load(path).headless_browser is True


def test_answer_profile_export_import_is_answer_only(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    source = AppConfig(
        resume_path="/private/cv.pdf",
        chrome_profile_dir="/private/chrome",
        output_csv="/private/applications.csv",
        default_numeric_answer="4",
        default_text_answer="See CV",
        default_boolean_answer="Yes",
        social_question_strategy="prefer_not_to_say",
        profile_answers={"ie_work_authorized": "Yes"},
        answers={"Custom recruiter question?": "My answer"},
    ).normalized()
    export_path = tmp_path / "answers.json"
    source.export_answer_profile(export_path)
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "linkedin-easy-apply-answer-profile"
    assert "resume_path" not in payload
    assert "chrome_profile_dir" not in payload
    assert "output_csv" not in payload

    target = AppConfig(profile_answers={"keep_me": "Current"}, answers={"old?": "Old"}).normalized()
    summary = target.import_answer_profile(export_path, replace=False)
    assert summary["mode"] == "merge"
    assert target.default_numeric_answer == "4"
    assert target.profile_answers["keep_me"] == "Current"
    assert target.profile_answers["ie_work_authorized"] == "Yes"
    assert target.answers["custom recruiter question"] == "My answer"


def test_answer_profile_replace_clears_old_explicit_answers(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    export_path = tmp_path / "answers.json"
    AppConfig(profile_answers={"ie_work_authorized": "Yes"}, answers={"q?": "A"}).export_answer_profile(export_path)
    target = AppConfig(profile_answers={"old": "value"}, answers={"old q?": "old"}).normalized()
    target.import_answer_profile(export_path, replace=True)
    assert "old" not in target.profile_answers
    assert "old q" not in target.answers


def test_fallback_defaults_are_normalized():
    config = AppConfig(default_numeric_answer="3,5", default_boolean_answer="true").normalized()
    assert config.default_numeric_answer == "3.5"
    assert config.default_boolean_answer == "Yes"
    invalid = AppConfig(default_numeric_answer="three", default_boolean_answer="maybe").normalized()
    assert invalid.default_numeric_answer == "0"
    assert invalid.default_boolean_answer == "No"


def test_answer_profile_export_contains_all_catalog_questions_even_blank(tmp_path, monkeypatch):
    import json
    from linkedin_easy_apply.question_catalog import QUESTION_CATALOG

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config = AppConfig(profile_answers={"ie_work_authorized": "Yes"}).normalized()
    export_path = tmp_path / "complete-answers.json"
    config.export_answer_profile(export_path)
    payload = json.loads(export_path.read_text(encoding="utf-8"))

    assert payload["version"] == 2
    assert len(payload["questions"]) == len(QUESTION_CATALOG)
    assert len(payload["profile_answers"]) == len(QUESTION_CATALOG)
    assert set(payload["profile_answers"]) == {q.key for q in QUESTION_CATALOG}
    assert payload["profile_answers"]["ie_work_authorized"] == "Yes"
    assert any(item["answer"] == "" for item in payload["questions"])
    assert all("question" in item and "answer" in item for item in payload["questions"])


def test_answer_profile_import_accepts_complete_questions_array(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    payload = {
        "schema": "linkedin-easy-apply-answer-profile",
        "version": 2,
        "defaults": {},
        "profile_answers": {"ie_work_authorized": ""},
        "questions": [
            {"key": "ie_work_authorized", "question": "Legally authorised to work in Ireland", "answer": "Yes"},
            {"key": "ie_sponsorship", "question": "Require sponsorship", "answer": ""},
        ],
        "learned_answers": {},
    }
    path = tmp_path / "complete.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    target = AppConfig()
    summary = target.import_answer_profile(path, replace=True)
    assert target.profile_answers["ie_work_authorized"] == "Yes"
    assert "ie_sponsorship" not in target.profile_answers
    assert summary["profile_answers"] == 1


def test_theme_name_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "settings.json"
    AppConfig(theme_name="Midnight").save(path)
    assert AppConfig.load(path).theme_name == "Midnight"


def test_failsafe_and_onboarding_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "settings.json"
    AppConfig(failsafe_seconds=75, onboarding_completed=True).save(path)
    loaded = AppConfig.load(path)
    assert loaded.failsafe_seconds == 75
    assert loaded.onboarding_completed is True
    assert AppConfig(failsafe_seconds=1).normalized().failsafe_seconds == 15
    assert AppConfig(failsafe_seconds=5000).normalized().failsafe_seconds == 900


def test_remember_answer_preserves_display_label_and_canonical_key():
    config = AppConfig().normalized()
    config.remember_answer("Você tem experiência com Python?", "Sim")
    assert config.answers["voce tem experiencia com python"] == "Sim"
    assert config.answer_labels["voce tem experiencia com python"] == "Você tem experiência com Python?"


def test_post_open_location_filter_defaults_off_even_with_legacy_strict_field():
    config = AppConfig().normalized()
    assert config.strict_location_filter is False  # legacy gate forced off
    assert config.post_open_location_filter is False


def test_post_open_location_filter_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    AppConfig(post_open_location_filter=True).save(path)
    assert AppConfig.load(path).post_open_location_filter is True


def test_default_delay_is_conservative_and_aggressive_delay_is_detected():
    config = AppConfig().normalized()
    assert config.min_delay_seconds == RECOMMENDED_MIN_DELAY_SECONDS
    assert config.max_delay_seconds == RECOMMENDED_MAX_DELAY_SECONDS
    assert delay_is_aggressive(1, 2) is True
    assert delay_is_aggressive(2, 4) is True
    assert delay_is_aggressive(3, 7) is False
    assert "does not publish a guaranteed safe interval" in delay_warning_text(1, 2)
    assert "soft ban" in delay_warning_text(1, 2).lower()


def test_field_signature_answers_roundtrip(tmp_path):
    from linkedin_easy_apply.config import AppConfig
    path = tmp_path / "config.json"
    cfg = AppConfig(run_mode="automatic")
    cfg.remember_answer("Question", "Answer", signature="radio|field-x|component-1")
    cfg.save(path)
    loaded = AppConfig.load(path)
    assert loaded.answer_signatures
    assert next(iter(loaded.answer_signatures.values())) == "Answer"


def test_run_disclaimer_defaults_visible_and_persists_boolean():
    assert AppConfig().normalized().show_run_disclaimer is True
    assert AppConfig(show_run_disclaimer=False).normalized().show_run_disclaimer is False


def test_zero_limits_mean_unlimited_or_until_exhausted():
    config = AppConfig(max_applications=0, max_pages_per_search=0).normalized()
    assert config.max_applications == 0
    assert config.max_pages_per_search == 0


def test_old_strict_location_config_does_not_reenable_post_open_filter(tmp_path):
    import json
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({
        "positions": ["AI Engineer"],
        "locations": ["Dublin, County Dublin, Ireland"],
        "strict_location_filter": True
    }), encoding="utf-8")
    loaded = AppConfig.load(path)
    assert loaded.strict_location_filter is False
    assert loaded.post_open_location_filter is False


def test_empty_locations_default_to_worldwide_not_dublin(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config = AppConfig(locations=[]).normalized()
    assert config.locations == ["Worldwide"]


def test_remote_and_country_search_locations_are_not_rewritten_to_dublin():
    from urllib.parse import parse_qs, urlparse
    from linkedin_easy_apply.bot import build_search_url
    from linkedin_easy_apply.config import resolve_search_location

    assert resolve_search_location("Remote") == "Worldwide"
    assert resolve_search_location("Worldwide") == "Worldwide"
    assert resolve_search_location("Portugal") == "Portugal"
    assert resolve_search_location("São Paulo, Brazil") == "São Paulo, Brazil"

    remote_url = build_search_url(AppConfig(work_types=[2]).normalized(), "AI Engineer", "Remote")
    remote_params = parse_qs(urlparse(remote_url).query)
    assert remote_params["location"] == ["Worldwide"]
    assert remote_params["f_WT"] == ["2"]

    portugal_url = build_search_url(AppConfig().normalized(), "AI Engineer", "Portugal")
    portugal_params = parse_qs(urlparse(portugal_url).query)
    assert portugal_params["location"] == ["Portugal"]
    assert portugal_params["keywords"] == ["AI Engineer"]


def test_atomic_save_preserves_previous_settings_on_replace_failure(tmp_path, monkeypatch):
    import pytest
    import linkedin_easy_apply.config as module

    path = tmp_path / "config.json"
    AppConfig(positions=["Original"]).save(path)
    before = path.read_bytes()
    def fail_replace(*args):
        raise PermissionError("Folder is locked")
    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        AppConfig(positions=["Unsaved edit"]).save(path)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_atomic_save_leaves_no_temporary_files(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(positions=["Data Analyst"])
    config.save(path)
    config.phone_number = "12345"
    config.save(path)
    assert AppConfig.load(path).phone_number == "12345"
    assert list(tmp_path.iterdir()) == [path]
